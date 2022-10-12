"""
created by gsnoep on 11 August 2022, extract_analytic_geo method adapted from 'extract_miller_from_eqdsk.py' by dtold

Module to handle any and all methods related to local magnetic geometry parametrisation.

The LocalEquilibrium Class can:
- parametrise a set of flux surface coordinates 
-
-

"""
import numpy as np
import matplotlib.pyplot as plt
import time
import copy

from scipy import interpolate
from scipy.optimize import least_squares
from sys import stdout

from .utils import *

class LocalEquilibrium():
    def __init__(self,method,equilibrium,x_loc,x_label='rho_tor',lref='a',cost_f='l1l2',n_x=10,n_theta=7200,n_harmonics=1,incl_analytic_geo=False,opt_bpol=False,diag_lsq=0,verbose=True):
        self._methods = {'miller':{
                             'param':self.miller,
                             'param_initial':[0.,0.,0.,1.,0.],
                             'param_bounds':([0.,-np.inf,0.,0.,-np.inf],np.inf),
                             'param_labels':['R0','Z0','r','kappa','delta'],
                             'bpol_param':self.miller_bp,
                             'bpol_initial':[0.,0.,0.,0.],
                             'bpol_bounds':[-np.inf,np.inf],
                             'bpol_labels':['dR0dr','dZ0dr','s_kappa','s_delta'],
                         },
                         'turnbull':{
                             'param':self.turnbull,
                             'param_initial':[0.,0.,0.,1.,0.,0.],
                             'param_bounds':([0.,-np.inf,0.,0.,-np.inf,-np.inf],np.inf),
                             'param_labels':['R0','Z0','r','kappa','delta','zeta'],
                             'bpol_param':self.turnbull_bp,
                             'bpol_initial':[0.,0.,0.,0.,0.],
                             'bpol_bounds':[-np.inf,np.inf],
                             'bpol_labels':['dR0dr','dZ0dr','s_kappa','s_delta','s_zeta'],
                         },
                         'turnbull_tilt':{
                             'param':self.turnbull_tilt,
                             'param_initial':[0.,0.,0.,1.,0.,0.,0.],
                             'param_bounds':([0.,-np.inf,0.,0.,-np.inf,-np.inf,-np.inf],np.inf),
                             'param_labels':['R0','Z0','r','kappa','delta','zeta','tilt'],
                             'bpol_param':self.turnbull_tilt_bp,
                             'bpol_initial':[0.,0.,0.,0.,0.,0.],
                             'bpol_bounds':[-np.inf,np.inf],
                             'bpol_labels':['dR0dr','dZ0dr','s_kappa','s_delta','s_zeta','s_tilt'],
                         },
                         'miller_general':{
                             'param':self.miller_general,
                             'param_initial':list(np.zeros(2+4*n_harmonics)),
                             'param_bounds':[-5,5],
                             'param_labels':['aR_0','aZ_0']+[label for sublist in [['aR_{}'.format(n),'bR_{}'.format(n),'aZ_{}'.format(n),'bZ_{}'.format(n)] for n in range(1,n_harmonics+1)] for label in sublist],
                             'bpol_param':self.miller_bp,
                             'bpol_initial':list(np.ones(2+4*n_harmonics)),
                             'bpol_bounds':[-np.inf,np.inf],
                             'bpol_labels':['d{}dr'.format(label) for label in ['aR_0','aZ_0']+[label for sublist in [['aR_{}'.format(n),'bR_{}'.format(n),'aZ_{}'.format(n),'bZ_{}'.format(n)] for n in range(1,n_harmonics+1)] for label in sublist]],
                         },
                         'mxh':{
                             'param':self.mxh,
                             'param_initial':list(np.zeros(5+2*n_harmonics)),
                             'param_bounds':[-np.inf,np.inf],
                             'param_labels':['R0','Z0','r','kappa','c_0']+[label for sublist in [['c_{}'.format(n),'s_{}'.format(n),] for n in range(1,n_harmonics+1)] for label in sublist],
                             'bpol_param':self.miller_bp,
                             'bpol_initial':list(np.ones(4+2*n_harmonics)),
                             'bpol_bounds':[-np.inf,np.inf],
                             'bpol_labels':['dR0dr','dZ0dr','s_kappa','dc_0dr']+[label for sublist in [['dc_{}dr'.format(n),'ds_{}dr'.format(n),] for n in range(1,n_harmonics+1)] for label in sublist],
                         }
        }

        self.verbose = verbose
        self.tolerance = 2.23e-16
        self.cost_param_f = cost_f
        self.x_loc = x_loc
        self.x_label = x_label

        # copy the equilibrium
        self.eq = copy.deepcopy(equilibrium)

        # initialise the LocalEquilibrium object methods consistent with the method input
        self.method = method
        self.param = self._methods[self.method]['param']
        self.param_initial = self._methods[self.method]['param_initial']
        self.param_bounds = self._methods[self.method]['param_bounds']
        self.param_labels = self._methods[self.method]['param_labels']
        self.bpol_param = self._methods[self.method]['bpol_param']
        self.bpol_initial = self._methods[self.method]['bpol_initial']
        self.bpol_bounds = self._methods[self.method]['bpol_bounds']
        self.bpol_labels = self._methods[self.method]['bpol_labels']

        self.n_x = n_x
        self.n_theta = n_theta
        # use case 1: standalone CLI call
        if self.n_x > 1:
            # setup the radial grid
            _x_list = list(np.linspace(self.x_loc-self.x_loc*0.005,self.x_loc,int(self.n_x/2)))
            x_list_ = list(np.linspace(self.x_loc,self.x_loc+self.x_loc*0.005,int(self.n_x/2)))
            self.x_grid = [x for x in (_x_list[:-1]+x_list_) if 0. <= x <= 1.]

            # extract flux surfaces
            self.eq.fluxsurfaces = {}
            self.eq.add_fluxsurfaces(x=self.x_grid,x_label=x_label,incl_analytic_geo=True,incl_B=[x==self.x_loc for x in self.x_grid],verbose=self.verbose)
        # use case 2: integrated in Equilibrium API
        else:
            self.x_grid = [self.x_loc]

        self.eq.fluxsurfaces['fit_geo'] = {}
        theta_min = 0
        theta_max = 2*np.pi
        for theta in self.eq.fluxsurfaces['theta_RZ']:
            if np.min(theta) > theta_min:
                theta_min = np.min(theta)
            if np.max(theta) < theta_max:
                theta_max = np.max(theta)
        self.theta = np.linspace(theta_min,theta_max,self.n_theta)

        opt_timing = 0.
        print('Optimising parametrisation fit of fluxsurfaces...')
        for i_x_loc,xfs in enumerate(self.x_grid):
            if self.verbose:
                # print a progress %
                stdout.write('\r {}% completed'.format(round(100*(find(xfs,self.x_grid)+1)/len(self.x_grid))))
                stdout.flush()
            # per flux surface extract a dict with all the values from the equilibrium
            self.fs = {}
            for key in set(['R','Z','R0','Z0','theta_RZ','r','psi']+self.param_labels):
                if key in self.eq.fluxsurfaces:
                    quantity = copy.deepcopy(self.eq.fluxsurfaces[key][i_x_loc])
                    if isinstance(quantity,list):
                        self.fs.update({key:np.array(quantity)})
                    else:
                        self.fs.update({key:quantity})

            if 'miller_geo' in self.eq.fluxsurfaces:
                self.fs['miller_geo'] = {}
                for key in self.eq.fluxsurfaces['miller_geo']:
                    quantity = copy.deepcopy(self.eq.fluxsurfaces['miller_geo'][key][i_x_loc])
                    if isinstance(quantity,list):
                        self.fs['miller_geo'].update({key:np.array(quantity)})
                    else:
                        self.fs['miller_geo'].update({key:quantity})

            #self.fs['theta_RZ'] = arctan2pi(self.fs['Z']-self.fs['Z0'],self.fs['R']-self.fs['R0'])
            #self.theta = np.linspace(np.min(self.fs['theta_RZ']),np.max(self.fs['theta_RZ']),self.n_theta)
            
            # check if there are values for the shape parameters that can be used as initial condition
            for i_key,key in enumerate(self.param_labels):
                if key in self.fs['miller_geo']:
                    self.param_initial[i_key] = copy.deepcopy(self.fs['miller_geo'][key])
                elif key in self.fs:
                    self.param_initial[i_key] = copy.deepcopy(self.fs[key])

            self.R_geo, self.Z_geo, self.theta_ref_geo = self.param(self.param_initial, np.append(self.theta,self.theta[0]), norm=False)
            self.R_ref_geo = np.array(interpolate.interp1d(self.fs['theta_RZ'], self.fs['R'], bounds_error=False, fill_value='extrapolate')(self.theta_ref_geo))
            self.Z_ref_geo = np.array(interpolate.interp1d(self.fs['theta_RZ'], self.fs['Z'], bounds_error=False, fill_value='extrapolate')(self.theta_ref_geo))

            '''plt.figure()
            plt.plot(self.R_ref_geo,self.Z_ref_geo)
            plt.axis('scaled')'''

            time0 = time.time()
            # compute the optimised shape parameters
            self.params = least_squares(self.cost_param, 
                                        self.param_initial, 
                                        bounds=self.param_bounds, 
                                        ftol=self.tolerance, 
                                        xtol=self.tolerance, 
                                        gtol=self.tolerance, 
                                        loss='soft_l1', 
                                        verbose=diag_lsq)['x']
            opt_timing += time.time()-time0

            # add the final parameterised and interpolated 
            params_keys = ['theta', 'R_param', 'Z_param', 'theta_ref', 'R_ref', 'Z_ref','R_ref_geo', 'Z_ref_geo']
            params_values = [self.theta, self.R_param+self.params[0], self.Z_param+self.params[1], self.theta_ref, self.R_ref+self.params[0], self.Z_ref+self.params[1], self.R_ref_geo, self.Z_ref_geo]
            
            for i_key,key in enumerate(params_keys):
                self.fs.update({key:copy.deepcopy(params_values[i_key])})

            # if the current flux surface is the one at self.x_loc, set the shape parameters
            if xfs == self.x_loc:
                self.shape = copy.deepcopy(self.params)

            # label and add the optimised shape parameters to the flux surface dict
            for i_key, key in enumerate(self.param_labels):
                self.fs.update({key:self.params[i_key]})
            
            del self.fs['R']
            del self.fs['Z']
            del self.fs['theta_RZ']
            del self.fs['miller_geo']

            merge_trees(self.fs,self.eq.fluxsurfaces['fit_geo'])
        if self.verbose:
            stdout.write('\n')
        list_to_array(self.eq.fluxsurfaces['fit_geo'])
        opt_timing /= len(self.x_grid)
        print('Optimization time pp:{}'.format(opt_timing))

        # re-set the LocalEquilibrium state variables to the x_loc values
        self.theta = copy.deepcopy(self.eq.fluxsurfaces['fit_geo']['theta'][self.x_grid.index(self.x_loc)])
        self.R_param, self.Z_param, self.theta_ref = self.param(self.shape, np.append(self.theta,self.theta[0]), norm=False)
        self.Bt_param = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.fs['psi'])/(self.R_param[:-1])

        # interpolate the actual flux surface contour to the theta basis 
        self.R_ref = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)], self.eq.fluxsurfaces['R'][self.x_grid.index(self.x_loc)], bounds_error=False, fill_value='extrapolate')(self.theta_ref))
        self.Z_ref = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)], self.eq.fluxsurfaces['Z'][self.x_grid.index(self.x_loc)], bounds_error=False, fill_value='extrapolate')(self.theta_ref))
        self.Bt_ref  = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.eq.fluxsurfaces['psi'][self.x_grid.index(self.x_loc)])/(self.R_ref[:-1])

        # compute the local gradients
        self.dxdr = np.gradient(self.eq.fluxsurfaces[x_label],self.eq.fluxsurfaces['fit_geo']['r'],edge_order=2)
        self.dpsidr = (self.dxdr*np.gradient(self.eq.fluxsurfaces['psi'],np.array(self.eq.fluxsurfaces[x_label])))[self.x_grid.index(self.x_loc)]

        self.shape_bpol = []
        s_deriv = {}
        if 'kappa' in self.param_labels:
            s_deriv.update({'s_kappa':self.eq.fluxsurfaces['fit_geo']['r']*self.dxdr*np.gradient(np.log(self.eq.fluxsurfaces['fit_geo']['kappa']),np.array(self.eq.fluxsurfaces[x_label]),edge_order=2)})
        if 'delta' in self.param_labels:
            s_deriv.update({'s_delta':(self.eq.fluxsurfaces['fit_geo']['r']/np.sqrt(1-self.eq.fluxsurfaces['fit_geo']['delta']**2))*self.dxdr*np.gradient(self.eq.fluxsurfaces['fit_geo']['delta'],np.array(self.eq.fluxsurfaces[x_label]),edge_order=2)})
        if 'zeta' in self.param_labels:
            s_deriv.update({'s_zeta':self.eq.fluxsurfaces['fit_geo']['r']*self.dxdr*np.gradient(self.eq.fluxsurfaces['fit_geo']['zeta'],np.array(self.eq.fluxsurfaces[x_label]),edge_order=2)}) 
        if 'tilt' in self.param_labels:
            s_deriv.update({'s_tilt':self.eq.fluxsurfaces['fit_geo']['r']*self.dxdr*np.gradient(self.eq.fluxsurfaces['fit_geo']['tilt'],np.array(self.eq.fluxsurfaces[x_label]),edge_order=2)}) 

        for i_key,key in enumerate(self.bpol_labels):
            if key in s_deriv.keys():
                self.eq.fluxsurfaces['fit_geo'][key] = s_deriv[key]
            else:
                self.eq.fluxsurfaces['fit_geo'][key] = self.dxdr*np.gradient(np.array(self.eq.fluxsurfaces['fit_geo'][self.param_labels[i_key]]),np.array(self.eq.fluxsurfaces[x_label]),edge_order=2)

            self.shape_bpol.append(self.eq.fluxsurfaces['fit_geo'][key][self.x_grid.index(self.x_loc)])

        if self.method in ['miller','turnbull','turnbull_tilt']:
            self.Bp_param = self.bpol_param(self.shape_bpol, self.shape, self.theta, self.R_param[:-1], self.dpsidr)
            self.Bp_ref = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)][:-1],self.eq.fluxsurfaces['Bpol'][self.x_grid.index(self.x_loc)][:-1],bounds_error=False,fill_value='extrapolate')(self.theta_ref[:-1]))
            self.shape_bpol_ref = copy.deepcopy(self.shape_bpol)
        if incl_analytic_geo:
            print('Computing analytical Miller geometry quantities...')
            self.shape_analytic = []
            for key in self._methods['turnbull']['param_labels']:
                if '0' in key:
                    key = key.replace('0','o')
                if key in self.eq.derived:
                    self.shape_analytic.append(self.eq.derived[key][self.x_grid.index(self.x_loc)])
                elif key in self.eq.derived['miller_geo']:
                    self.shape_analytic.append(self.eq.derived['miller_geo'][key][self.x_grid.index(self.x_loc)])
            self.shape_bpol_analytic = []
            for key in self._methods['turnbull']['bpol_labels']:
                if '0' in key:
                    key = key.replace('0','o')
                if key in self.eq.derived:
                    self.shape_bpol_analytic.append(self.eq.derived[key][self.x_grid.index(self.x_loc)])
                elif key in self.eq.derived['miller_geo']:
                    self.shape_bpol_analytic.append(self.eq.derived['miller_geo'][key][self.x_grid.index(self.x_loc)])
                        
            self.R_geo, self.Z_geo, self.theta_ref_geo = self.turnbull(self.shape_analytic, np.append(self.theta,self.theta[0]), norm=False)
            self.Bt_geo = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.eq.fluxsurfaces['psi'][self.x_grid.index(self.x_loc)])/(self.R_geo[:-1])

            self.R_ref_geo = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)], self.eq.fluxsurfaces['R'][self.x_grid.index(self.x_loc)], bounds_error=False, fill_value='extrapolate')(self.theta_ref_geo))
            self.Z_ref_geo = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)], self.eq.fluxsurfaces['Z'][self.x_grid.index(self.x_loc)], bounds_error=False, fill_value='extrapolate')(self.theta_ref_geo))
            self.Bt_ref_geo  = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.eq.fluxsurfaces['psi'][self.x_grid.index(self.x_loc)])/(self.R_ref_geo[:-1])

            self.Bp_geo = self.turnbull_bp(self.shape_bpol_analytic, self.shape_analytic, self.theta, self.R_geo[:-1], self.dpsidr)
            self.Bp_ref_geo = np.array(interpolate.interp1d(self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)][:-1],self.eq.fluxsurfaces['Bpol'][self.x_grid.index(self.x_loc)][:-1],bounds_error=False,fill_value='extrapolate')(self.theta_ref_geo[:-1]))

        if opt_bpol:
            print('Optimising Bpol parametrisation fit...')
            self.bpol_initial = copy.deepcopy(self.shape_bpol)

            self.shape_bpol = least_squares(self.cost_bpol, 
                                            self.bpol_initial, 
                                            bounds=self.bpol_bounds, 
                                            ftol=self.tolerance, 
                                            xtol=self.tolerance, 
                                            gtol=self.tolerance, 
                                            loss='soft_l1', 
                                            verbose=diag_lsq)['x']
            
            for i_key,key in enumerate(self.bpol_labels):
                self.eq.fluxsurfaces['fit_geo'][key+'_opt'] = copy.deepcopy(self.shape_bpol[i_key])
        
    # shape factor method Miller parameterisations
    def miller(self,params,theta,norm=False):
        # flux surface coordinate parameterisation from [Miller PoP 5 (1998)]
        [R0,Z0,r,kappa,delta] = params
        with np.errstate(invalid=='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta)

        R_param = R0 + r * np.cos(theta_R)
        Z_param = Z0 + kappa * r * np.sin(theta)

        theta_ref = arctan2pi(Z_param-Z0,R_param-R0)
        if norm:
            R_param-=R0
            Z_param-=Z0
        
        return R_param, Z_param, theta_ref

    def miller_bp(self,params,shape,theta,R,dPsi_dr,method='analytical'):
        # define the parameters
        [R0,Z0,r,kappa,delta] = shape
        [dR0dr,dZ0dr,s_kappa,s_delta] = params
        with np.errstate(invalid='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta)

        if method == 'analytical':
            Bp_nom = np.sqrt(np.sin(theta_R)**2 + (1 + x * np.cos(theta))**2 + kappa**2 * np.cos(theta)**2)
            Bp_denom = np.cos(x * np.sin(theta)) + dR0dr * np.cos(theta) + (s_kappa - s_delta * np.cos(theta) + (1+ s_kappa) * x * np.cos(theta)) * np.sin(theta) * np.sin(theta_R)

            Bp_param = (dPsi_dr / (R * kappa)) * Bp_nom / Bp_denom
        
        elif method == 'numerical':
            # compute the derivatives for the jacobian
            dRdtheta = - r * np.sin(theta_R)(1 + x * np.cos(theta))
            dZdtheta = kappa * r * np.cos(theta)
            dRdr = dR0dr + np.cos(theta_R) - s_delta * np.sin(theta) * np.sin(theta_R)
            dZdr = kappa * (s_kappa + 1) * np.sin(theta)

            # compute the jacobian and the Mercier-Luc arclength derivative
            J_r = R * (dRdr * dZdtheta - dRdtheta * dZdr)
            dl_dtheta = np.sqrt(dRdtheta**2 + dZdtheta**2)

            # compute |grad r|
            grad_r_norm = (R/J_r)*dl_dtheta

            # Poloidal magnetic flux density
            Bp_param = (dPsi_dr/R) * grad_r_norm

        return Bp_param

    def turnbull(self,params,theta,norm=False):
        # flux surface coordinate parameterisation from [Turnbull PoP 6 (1999)]
        [R0,Z0,r,kappa,delta,zeta] = params
        with np.errstate(invalid='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta)
        theta_Z = theta + zeta * np.sin(2 * theta)

        R_param = R0 + r * np.cos(theta_R)
        Z_param = Z0 + kappa * r * np.sin(theta_Z)
        theta_ref = arctan2pi(Z_param-Z0,R_param-R0)
        
        if norm:
            R_param-=R0
            Z_param-=Z0
        
        return R_param, Z_param, theta_ref

    def turnbull_bp(self,params,shape,theta,R,dPsi_dr,method='analytical'):
        # define the parameters
        [R0,Z0,r,kappa,delta,zeta] = shape
        [dR0dr,dZ0dr,s_kappa,s_delta,s_zeta] = params
        with np.errstate(invalid='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta)
        dtheta_Rdtheta = 1 + x * np.cos(theta)
        theta_Z = theta + zeta * np.sin(2 * theta)
        dtheta_Zdtheta = 1 + 2 * zeta * np.cos(2 * theta)

        if method == 'analytical':
            Bp_nom = np.sqrt(np.sin(theta_R)**2 * dtheta_Rdtheta**2 + kappa**2 * np.cos(theta_Z)**2 * dtheta_Zdtheta**2)
            Bp_denom = kappa * np.cos(theta_Z) * dtheta_Zdtheta * (dR0dr + np.cos(theta_R) - s_delta * np.sin(theta) * np.sin(theta_R)) + np.sin(theta_R) * dtheta_Rdtheta * (dZ0dr + kappa * ((s_kappa + 1) * np.sin(theta_Z) + s_zeta * np.sin(2 * theta) * np.cos(theta_Z)))

            Bp_param = (dPsi_dr / R) * Bp_nom / Bp_denom
        
        elif method == 'numerical':
            # compute the derivatives for the jacobian
            dRdtheta = - r * np.sin(theta_R) * dtheta_Rdtheta
            dZdtheta = kappa * r * np.cos(theta_Z) * (1 + 2 * zeta * np.cos(2 * theta))
            dRdr = dR0dr + np.cos(theta_R) - s_delta * np.sin(theta) * np.sin(theta_R)
            dZdr = dZ0dr + kappa * ((s_kappa + 1) * np.sin(theta_Z) + s_zeta * np.sin(2 * theta) * np.cos(theta_Z))

            # compute the jacobian and the Mercier-Luc arclength derivative
            J_r = R * (dRdr * dZdtheta - dRdtheta * dZdr)
            dl_dtheta = np.sqrt(dRdtheta**2 + dZdtheta**2)

            # compute |grad r|
            grad_r_norm = (R/J_r)*dl_dtheta

            # Poloidal magnetic flux density
            Bp_param = (dPsi_dr/R) * grad_r_norm

        return Bp_param

    def turnbull_tilt(self,params,theta,norm=False):
        # flux surface coordinate parameterisation from [Turnbull PoP 6 (1999)]
        [R0,Z0,r,kappa,delta,zeta,tilt] = params
        with np.errstate(invalid='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta) + tilt
        theta_Z = theta + zeta * np.sin(2 * theta)

        R_param = R0 + r * np.cos(theta_R)
        Z_param = Z0 + kappa * r * np.sin(theta_Z)

        theta_ref = arctan2pi(Z_param-Z0,R_param-R0)
        
        if norm:
            R_param-=R0
            Z_param-=Z0

        return R_param, Z_param, theta_ref

    def turnbull_tilt_bp(self,params,shape,theta,R,dPsi_dr,method='numerical'):
        # define the parameters
        [R0,Z0,r,kappa,delta,zeta,tilt] = shape
        [dR0dr,dZ0dr,s_kappa,s_delta,s_zeta,s_tilt] = params
        with np.errstate(invalid='ignore'):
            x = np.arcsin(delta)
        theta_R = theta + x * np.sin(theta) + tilt
        dtheta_Rdtheta = 1 + x * np.cos(theta)
        theta_Z = theta + zeta * np.sin(2 * theta)
        dtheta_Zdtheta = 1 + 2 * zeta * np.cos(2 * theta)

        if method == 'analytical':
            Bp_nom = np.sqrt(np.sin(theta_R)**2 * dtheta_Rdtheta**2 + kappa**2 * np.cos(theta_Z)**2 * dtheta_Zdtheta**2)
            Bp_denom = kappa * np.cos(theta_Z) * dtheta_Zdtheta * (dR0dr + np.cos(theta_R) - s_delta * np.sin(theta) * np.sin(theta_R) + s_tilt) + np.sin(theta_R) * dtheta_Rdtheta * (dZ0dr + kappa * ((s_kappa + 1) * np.sin(theta_Z) + s_zeta * np.sin(2 * theta) * np.cos(theta_Z)))

            Bp_param = (dPsi_dr / R) * Bp_nom / Bp_denom
        
        elif method == 'numerical':
            # compute the derivatives for the jacobian
            dRdtheta = - r * np.sin(theta_R) * dtheta_Rdtheta
            dZdtheta = kappa * r * np.cos(theta_Z) * (1 + 2 * zeta * np.cos(2 * theta))
            dRdr = dR0dr + np.cos(theta_R) - s_delta * np.sin(theta) * np.sin(theta_R) + s_tilt
            dZdr = dZ0dr + kappa * ((s_kappa + 1) * np.sin(theta_Z) + s_zeta * np.sin(2 * theta) * np.cos(theta_Z))

            # compute the jacobian and the Mercier-Luc arclength derivative
            J_r = R * (dRdr * dZdtheta - dRdtheta * dZdr)
            dl_dtheta = np.sqrt(dRdtheta**2 + dZdtheta**2)

            # compute |grad r|
            grad_r_norm = (R/J_r)*dl_dtheta

            # Poloidal magnetic flux density
            Bp_param = (dPsi_dr/R) * grad_r_norm

        return Bp_param

    # Fourier method Miller-like parametrisations
    def miller_general(self,params,theta,norm=None):
        # flux surface coordinate parameterisation from [Candy PPCF 51 (2009)]
        [aR_0, aZ_0] = params[:2]
        R0 = 0.5 * aR_0
        Z0 = 0.5 * aZ_0
        R_fourier, Z_fourier = 0,0
        N = int((len(params)-2)/4)
        for n in range(1,N+1):
            aR_n = params[2 + (n-1)*4]
            bR_n = params[3 + (n-1)*4]
            aZ_n = params[4 + (n-1)*4]
            bZ_n = params[5 + (n-1)*4]
            R_fourier += aR_n * np.cos(n * theta) + bR_n * np.sin(n * theta)
            Z_fourier += aZ_n * np.cos(n * theta) + bZ_n * np.sin(n * theta)

        R_param = R0 + R_fourier
        Z_param = Z0 + Z_fourier

        theta_ref = arctan2pi(Z_param-Z0,R_param-R0)
        if norm:
            R_param-=R0
            Z_param-=Z0

        return R_param, Z_param, theta_ref

    def mxh(self,params,theta,norm=None):
        # flux surface coordinate parameterisation from [Arbon PPCF 61 (2021)]
        [R0,Z0,r,kappa,c_0] = params[:5]
        theta_R = theta + c_0
        N = int((len(params)-5)/2)
        for n in range(1,N+1):
            c_n = params[5 + (n-1)*2]
            s_n = params[6 + (n-1)*2]
            theta_R +=  c_n * np.cos(n * theta) + s_n * np.sin(n * theta)

        R_param = R0 + r * np.cos(theta_R)
        Z_param = Z0 + kappa * r * np.sin(theta)

        theta_ref = arctan2pi(Z_param-Z0,R_param-R0)

        if norm:
            R_param-=R0
            Z_param-=Z0

        return R_param, Z_param, theta_ref

    def cost_param(self,params):
        # compute the flux surface parameterisation for a given shape set `params`
        self.R_param, self.Z_param, self.theta_ref = self.param(params, np.append(self.theta,self.theta[0]), norm=True)

        # interpolate the actual flux surface contour to the theta basis 
        self.R_ref = np.array(interpolate.interp1d(self.fs['theta_RZ'], self.fs['R'], bounds_error=False, fill_value='extrapolate')(self.theta_ref)) - params[0]
        self.Z_ref = np.array(interpolate.interp1d(self.fs['theta_RZ'], self.fs['Z'], bounds_error=False, fill_value='extrapolate')(self.theta_ref)) - params[1]

        # define the cost function
        L1_norm = np.abs(np.array([self.R_param,self.Z_param])-np.array([self.R_ref,self.Z_ref])).flatten()
        L2_norm = np.sqrt((self.R_param-self.R_ref)**2+(self.Z_param-self.Z_ref)**2)

        if self.cost_param_f == 'l1l2':
            cost = self.n_theta*np.hstack((L2_norm,L1_norm))
        else:
            self.Bt_param = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.fs['psi'])/(self.R_param+params[0])
            self.Bt_ref  = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.fs['psi'])/(self.R_ref+params[0])
            if self.cost_param_f == 'Bt4':
                filter = self.Bt_ref**4
                cost = np.hstack((filter*L2_norm,L1_norm*np.hstack((filter,filter))))
            elif self.cost_param_f == 'l1Bt':
                L1_btor = self.Bt_ref**2*np.abs((self.Bt_param-self.Bt_ref))
                cost = self.n_theta*np.hstack((L1_norm,L1_btor))

        return cost
    
    def cost_bpol(self,params):
        self.Bp_param_opt = self.bpol_param(params, self.shape, self.theta, self.R_param[:-1], self.dpsidr)
        
        theta_RZ = self.eq.fluxsurfaces['theta_RZ'][self.x_grid.index(self.x_loc)][:-1]
        Bp_RZ = self.eq.fluxsurfaces['Bpol'][self.x_grid.index(self.x_loc)][:-1]
        self.Bp_ref_opt = np.array(interpolate.interp1d(theta_RZ,Bp_RZ,bounds_error=False,fill_value='extrapolate')(self.theta_ref[:-1]))

        cost = self.n_theta*np.abs(self.Bp_param_opt-self.Bp_ref_opt)#/self.self.Bp_ref

        # alternate cost functions
        #self.Bt_param = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.eq.fluxsurfaces['psi'][self.x_grid.index(self.x_loc)])/(self.R_param[:-1])
        #self.Bt_ref  = interpolate.interp1d(self.eq.derived['psi'],self.eq.derived['fpol'],bounds_error=False)(self.eq.fluxsurfaces['psi'][self.x_grid.index(self.x_loc)])/(self.R_ref[:-1])
        #cost = self.n_theta*((np.sqrt(self.Bp_ref**2+self.Bt_ref**2)-np.sqrt(self.Bp_param_opt**2+self.Bt_param**2)))
        #cost = ((np.sqrt(Bp_ref**2+Bt_ref**2)-np.sqrt(Bp_param**2+Bt_param**2))/np.sqrt(Bp_ref**2+Bt_ref**2))

        # alternative filters and weights
        '''filter = np.ones_like(self.Bp_ref)
        dBpoldtheta = np.gradient(self.Bp_ref,self.theta_ref)
        filter += 2*np.bitwise_and(dBpoldtheta>-0.1, dBpoldtheta<0.1)
        filter += 2*np.bitwise_and(dBpoldtheta >= 0.9*np.max(dBpoldtheta),dBpoldtheta <= np.max(dBpoldtheta))
        weights = filter#*(len(theta_ref)/B_pol_ref)'''
        '''filter = np.zeros_like(self.Bp_ref)
        dBpoldtheta = np.gradient(self.Bp_ref,self.theta_ref)
        filter += np.bitwise_and(dBpoldtheta>-0.1, dBpoldtheta<0.1)
        filter += 3*np.bitwise_and(self.Bp_ref <= 1.1*np.min(self.Bp_ref),self.Bp_ref >= np.min(self.Bp_ref))
        #filter += np.bitwise_and(dBpoldtheta >= 0.9*np.max(dBpoldtheta),dBpoldtheta <= np.max(dBpoldtheta))
        filter += np.bitwise_and(self.Bp_ref >= 0.925*np.mean(self.Bp_ref),self.Bp_ref <= 1.05*np.mean(self.Bp_ref))
        weights = filter#*(len(theta_ref)/B_pol_ref)'''

        '''dBpoldtheta = np.gradient(self.Bp_ref,self.theta_ref[:-1])
        
        filter = np.bitwise_and(dBpoldtheta>-0.075, dBpoldtheta<0.075)
        filter += np.bitwise_and(self.Bp_ref <= 1.2*np.min(self.Bp_ref),self.Bp_ref >= np.min(self.Bp_ref))
        filter += np.bitwise_and(self.Bp_ref >= 0.925*np.mean(self.Bp_ref),self.Bp_ref <= 1.075*np.mean(self.Bp_ref))'''
        
        '''filter = np.ones_like(self.Bp_ref)
        filter = np.bitwise_and(dBpoldtheta>-0.1, dBpoldtheta<0.1)
        filter += np.bitwise_and(dBpoldtheta >= 0.9*np.max(dBpoldtheta),dBpoldtheta <= np.max(dBpoldtheta))'''

        return cost#*(filter/self.Bp_ref)#*weights

    def extract_analytic_geo(fluxsurface):
        """Extract Turnbull-Miller geometry parameters [Turnbull PoP 6 1113 (1999)] from a flux surface contour. Adapted from 'extract_miller_from_eqdsk.py' by D. Told.

        Args:
            `fluxsurface` (dict): flux surface data containing R, Z, R0, Z0, r, theta_RZ (poloidal angle between R and Z) and the R_Zmax,Z_max and R_Zmin,Z_min coordinates.

        Returns:
            (dict): the Miller parameters and R_miller,Z_miller on the same poloidal basis as the input flux surface.
        """
        miller_geo = {}

        # compute triangularity (delta) and elongation (kappa) of flux surface
        miller_geo['delta_u'] = (fluxsurface['R0'] - fluxsurface['R_Zmax'])/fluxsurface['r']
        miller_geo['delta_l'] = (fluxsurface['R0'] - fluxsurface['R_Zmin'])/fluxsurface['r']
        miller_geo['delta'] = (miller_geo['delta_u']+miller_geo['delta_l'])/2
        x = np.arcsin(miller_geo['delta'])
        miller_geo['kappa'] = (fluxsurface['Z_max'] - fluxsurface['Z_min'])/(2*fluxsurface['r'])

        # generate theta grid and interpolate the flux surface trace to the Miller parameterisation
        R_miller = fluxsurface['R0'] + fluxsurface['r']*np.cos(fluxsurface['theta_RZ']+x*np.sin(fluxsurface['theta_RZ']))
        Z_miller = np.hstack((interpolate.interp1d(fluxsurface['R'][:np.argmin(fluxsurface['R'])],fluxsurface['Z'][:np.argmin(fluxsurface['R'])],bounds_error=False)(R_miller[:find(np.min(fluxsurface['R']),R_miller)]),interpolate.interp1d(fluxsurface['R'][np.argmin(fluxsurface['R']):],fluxsurface['Z'][np.argmin(fluxsurface['R']):],bounds_error=False)(R_miller[find(np.min(fluxsurface['R']),R_miller):])))

        # derive the squareness (zeta) from the Miller parametrisation
        theta_zeta = np.array([0.25*np.pi,0.75*np.pi,1.25*np.pi,1.75*np.pi])
        Z_zeta = np.zeros_like(theta_zeta)
        for i,quadrant in enumerate(theta_zeta):
            Z_zeta[i] = interpolate.interp1d(fluxsurface['theta_RZ'][find(quadrant-0.25*np.pi,fluxsurface['theta_RZ']):find(quadrant+0.25*np.pi,fluxsurface['theta_RZ'])],Z_miller[find(quadrant-0.25*np.pi,fluxsurface['theta_RZ']):find(quadrant+0.25*np.pi,fluxsurface['theta_RZ'])])(quadrant)

        # invert the Miller parametrisation of Z, holding off on subtracting theta/sin(2*theta)
        zeta_4q = np.arcsin((Z_zeta-fluxsurface['Z0'])/(miller_geo['kappa']*fluxsurface['r']))/np.sin(2*theta_zeta)

        # apply a periodic correction for the arcsin of the flux surface quadrants
        zeta_4q = np.array([1,-1,-1,1])*zeta_4q+np.array([0,-np.pi,-np.pi,0])

        miller_geo['zeta_uo'] = zeta_4q[0] - (theta_zeta[0]/np.sin(2*theta_zeta[0]))
        miller_geo['zeta_ui'] = zeta_4q[1] - (theta_zeta[1]/np.sin(2*theta_zeta[1]))
        miller_geo['zeta_li'] = zeta_4q[2] - (theta_zeta[1]/np.sin(2*theta_zeta[1]))
        miller_geo['zeta_lo'] = zeta_4q[3] - (theta_zeta[0]/np.sin(2*theta_zeta[0]))

        # compute the average squareness of the flux surface
        miller_geo['zeta'] = 0.25*(miller_geo['zeta_uo']+miller_geo['zeta_ui']+miller_geo['zeta_li']+miller_geo['zeta_lo'])

        miller_geo['R_miller'] = R_miller
        miller_geo['Z_miller'] = fluxsurface['Z0']+miller_geo['kappa']*fluxsurface['r']*np.sin(fluxsurface['theta_RZ']+miller_geo['zeta']*np.sin(2*fluxsurface['theta_RZ']))

        return miller_geo
    
    def printer(self,printer,shape,labels,shape_bpol,labels_bpol,lref='a'):
        print('Printing input values for {} code...'.format(printer))
        i_x_loc = self.x_grid.index(self.x_loc)

        fs = {}
        for i_key,key in enumerate(labels):
            fs.update({key:shape[i_key]})
        for i_key,key in enumerate(labels_bpol):
            fs.update({key:shape_bpol[i_key]})
        # get the other derived quantities required for print
        for key in ['q','s','fpol']:
            if key in self.eq.fluxsurfaces:
                fs.update({key:self.eq.fluxsurfaces[key][i_x_loc]})
            elif key in self.eq.derived:
                fs.update({key:self.eq.derived[key][i_x_loc]})

        if printer.lower() == 'gene':
            if lref == 'a':
                Lref = self.eq.derived['a']
            elif lref =='R':
                Lref = fs['R0']
            
            if self.method in ['miller','turnbull']:
                print('&geometry')
                print('trpeps  = {}\t! {} = {}'.format((fs['r']/fs['R0']),self.x_label,self.x_loc))
                print('q0      = {}'.format(fs['q']))
                print('shat    = {}'.format(fs['s']))
                print('amhd    = {}'.format(-1))
                print('drR     = {}'.format(fs['dR0dr']))
                print('drZ     = {}'.format(fs['dZ0dr']))
                print('kappa   = {}'.format(fs['kappa']))
                print('s_kappa = {}'.format(fs['s_kappa']))
                print('delta   = {}'.format(fs['delta']))
                print('s_delta = {}'.format(fs['s_delta']))
                if self.method == 'turnbull':
                    print('zeta    = {}'.format(fs['zeta']))
                    print('s_zeta  = {}'.format(fs['s_zeta']))
                if lref == 'a':
                    print('minor_r = {}'.format(1))#1.0,
                    print('major_R = {}'.format(fs['R0']/Lref))#R0/a,
                elif lref == 'R':
                    #print('\nFor normalization to major radius:')
                    print('minor_r = {}'.format(Lref/fs['R0']))#a/R0,
                    print('major_R = {}'.format(1))#1.0,
                print('/')
            
                print('\nAdditional information:')
                print('&units')
                if lref == 'a':
                    print('Lref    = {} !for Lref=a convention'.format(Lref))
                elif lref == 'R':
                    print('Lref    = {} !for Lref=R0 convention'.format(fs['R0']))
                print('Bref    = {}'.format(fs['fpol']/fs['R0']))
                print('/')

            else:
                print('The selected geometry parameterization is currently not supported by GENE!')
        
        elif printer.lower() == 'tglf':
            Lref = self.eq.derived['a']
            if self.method in ['miller','turnbull']:
                print('RMIN_LOC = {}'.format(fs['r']/Lref))
                print('RMAJ_LOC = {}'.format(fs['R0']/Lref))
                print('ZMAJ_LOC = {}'.format(fs['Z0']))
                print('DRMAJDX_LOC = {}'.format(fs['dR0dr']))
                print('DZMAJDX_LOC = {}'.format(fs['dZ0dr']))
                print('KAPPA_LOC = {}'.format(fs['kappa']))
                print('S_KAPPA_LOC = {}'.format(fs['s_kappa']))
                print('DELTA_LOC = {}'.format(fs['delta']))
                print('S_DELTA_LOC = {}'.format(fs['s_delta']*(1.0-fs['delta']**2.0)**0.5))
                if self.method == 'turnbull':
                    print('ZETA_LOC = {}'.format(fs['zeta']))
                    print('S_ZETA_LOC = {}'.format(fs['s_zeta']))
                print('Q_LOC = {}'.format(fs['q']))
                print('Q_PRIME_LOC = {}'.format(fs['s']*(fs['q']/(fs['r']/Lref))**2))
                #print('P_PRIME_LOC = {}'.format(-fs['amhd']/(8.0*np.pi*(fs['q']/Lref)*(fs['R0']/Lref)*fs['r'])))
            else:
                print('The selected geometry parameterization is currently not supported by TGLF!')
        else:
            print('Selected option {} is not supported for printing iput format! For fitted shape parameters see below:'.format(printer))
            for i_key,key in enumerate(self.param_labels):
                print('{} = {}'.format(key,self.shape[i_key]))
            for i_key,key in enumerate(self.bpol_labels):
                print('{} = {}'.format(key,self.shape_bpol[i_key]))

        return

    def plot_all(self,incl_analytic=None,opt_bpol=None):
        i_x_loc = self.x_grid.index(self.x_loc)

        fs = {}
        # get all the flux surface shape parameters
        for key in self.param_labels:
            if key in self.eq.fluxsurfaces['fit_geo']:
                fs.update({key:self.eq.fluxsurfaces['fit_geo'][key]})
        for key in self.bpol_labels:
            if key+'_opt' in self.eq.fluxsurfaces['fit_geo']:
                fs.update({key:self.eq.fluxsurfaces['fit_geo'][key+'_opt']})
            if key in self.eq.fluxsurfaces['fit_geo']:
                fs.update({key:self.eq.fluxsurfaces['fit_geo'][key]})
        # get the other derived quantities required for print
        for key in ['q','s','fpol']:
            if key in self.eq.fluxsurfaces:
                fs.update({key:self.eq.fluxsurfaces[key]})
            elif key in self.eq.derived:
                fs.update({key:self.eq.derived[key]})


        for i_key,key in enumerate(fs.keys()):
            if '_opt' not in key:
                plt.figure(i_key)
                plt.title(key)
                plt.plot(self.x_grid,fs[key])
            else:
                plt.figure(find(key.replace('_opt',''),list(fs.keys())))
                plt.title(key)
                plt.plot(self.x_loc,fs[key],'*')
        
        fig = plt.figure(constrained_layout=True,figsize=(15,10))
        fig.suptitle('MEGPy diagnostic'.format(self.x_label,self.x_loc))
        axes = fig.subplot_mosaic(
            """
            AACDEF
            AACDEF
            AAGHIJ
            BBGHIJ
            """
        )
        
        plt.show()

        return