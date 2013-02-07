import anuga
import numpy as num
import math
import parallel_inlet_enquiry 

from anuga.utilities.system_tools import log_to_file
from anuga.utilities.numerical_tools import ensure_numeric
from anuga.structures.inlet_enquiry import Inlet_enquiry
import pypar

class Parallel_Structure_operator(anuga.Operator):
    """Parallel Structure Operator - transfer water from one rectangular box to another.
    Sets up the geometry of problem
    
    This is the base class for structures (culverts, pipes, bridges etc) that exist across multiple
    parallel shallow water domains. Inherit from this class (and overwrite discharge_routine method 
    for specific subclasses)
    
    Input: Two points, pipe_size (either diameter or width, depth),
    mannings_rougness,
    """ 

    counter = 0

    """
     ===========================================================================================
     PETE: Inputs to this constructor are identical to the serial
     structure operator, except for the following arguments:
     master_proc - the processor that coordinates all processors (with domains) associated with this structure [INT]
     procs - the list of processors associated with thisstructure (List[INT])
     inlet_master_proc - master_proc of the first and second inlet (List[2])
     inlet_procs - list of processors associated with the first and second inlet (LIST[2][INT])
     enquiry_proc - processor associated the first and second enquiry point (List[2])
    """

    def __init__(self,
                 domain,
                 end_points,
                 exchange_lines,
                 enquiry_points,
                 width,
                 height,
                 apron,
                 manning,
                 enquiry_gap,
                 description,
                 label,
                 structure_type,
                 logging,
                 verbose,
                 master_proc = 0,
                 procs = None,
                 inlet_master_proc = [0,0],
                 inlet_procs = None,
                 enquiry_proc = None):

        self.myid = pypar.rank()
        self.num_procs = pypar.size()
        
        anuga.Operator.__init__(self,domain)

        # Allocate default processor associations if not specified in arguments
        # although we assume that such associations are provided correctly by the 
        # parallel_operator_factory.

        self.master_proc = master_proc
        self.inlet_master_proc = inlet_master_proc
        
        if procs is None:
            self.procs = [master_proc]
        else:
            self.procs = procs

        if inlet_procs is None:
            self.inlet_procs = [[inlet_master_proc[0]],[inlet_master_proc[0]]]
        else:
            self.inlet_procs = inlet_procs

        if enquiry_proc is None:
            self.enquiry_proc = [[inlet_master_proc[0]],[inlet_master_proc[0]]]
        else:
            self.enquiry_proc = enquiry_proc

        self.end_points = ensure_numeric(end_points)
        self.exchange_lines = ensure_numeric(exchange_lines)
        self.enquiry_points = ensure_numeric(enquiry_points)

        
        if height is None:
            height = width

        if apron is None:
            apron = width

        self.width  = width
        self.height = height
        self.apron  = apron
        self.manning = manning
        self.enquiry_gap = enquiry_gap

        if description == None:
            self.description = ' '
        else:
            self.description = description
        
        if label == None:
            self.label = "structure_%g" % Parallel_Structure_operator.counter + "_P" + str(self.myid)
        else:
            self.label = label + '_%g' % Parallel_Structure_operator.counter + "_P" + str(self.myid)

        if structure_type == None:
            self.structure_type = 'generic structure'
        else:
            self.structure_type = structure_type
            
        self.verbose = verbose        
        
        # Keep count of structures
        if self.myid == master_proc:
            Parallel_Structure_operator.counter += 1

        # Slots for recording current statistics
        self.discharge = 0.0
        self.velocity = 0.0
        self.delta_total_energy = 0.0
        self.driving_energy = 0.0
        
        if exchange_lines is not None:
            self.__process_skew_culvert()

        elif end_points is not None:
            self.__process_non_skew_culvert()
        else:
            raise Exception, 'Define either exchange_lines or end_points'
        
        self.inlets = []

        # Allocate parallel inlet enquiry, assign None if processor is not associated with particular
        # inlet.

        if self.myid in self.inlet_procs[0]:
            line0 = self.exchange_lines[0] 
            enquiry_point0 = self.enquiry_points[0]
            outward_vector0 = self.culvert_vector

            self.inlets.append(parallel_inlet_enquiry.Parallel_Inlet_enquiry(self.domain, line0,
                               enquiry_point0, self.inlet_master_proc[0], self.inlet_procs[0], 
                               self.enquiry_proc[0], outward_vector0, self.verbose))
        else:
            self.inlets.append(None)

        if self.myid in self.inlet_procs[1]:
            line1 = self.exchange_lines[1]
            enquiry_point1 = self.enquiry_points[1]
            outward_vector1  = - self.culvert_vector

            self.inlets.append(parallel_inlet_enquiry.Parallel_Inlet_enquiry(self.domain, line1,
                               enquiry_point1, self.inlet_master_proc[1],
                               self.inlet_procs[1], self.enquiry_proc[1], outward_vector1, self.verbose))
        else:
            self.inlets.append(None)

        self.inflow_index = 0
        self.outflow_index = 1

        self.set_parallel_logging(logging)

    def __call__(self):

        timestep = self.domain.get_timestep()

        Q, barrel_speed, outlet_depth = self.discharge_routine()

        # Get attributes of Inflow inlet, all procs associated with inlet must call
        if self.myid in self.inlet_procs[self.inflow_index]:
            old_inflow_depth = self.inlets[self.inflow_index].get_global_average_depth()
            old_inflow_stage = self.inlets[self.inflow_index].get_global_average_stage()
            old_inflow_xmom = self.inlets[self.inflow_index].get_global_average_xmom()
            old_inflow_ymom = self.inlets[self.inflow_index].get_global_average_ymom()
            inflow_area = self.inlets[self.inflow_index].get_global_area()

        # Master proc of inflow inlet sends attributes to master proc of structure
        if self.myid == self.master_proc:
            if self.myid != self.inlet_master_proc[self.inflow_index]:
                old_inflow_depth = pypar.receive(self.inlet_master_proc[self.inflow_index])
                old_inflow_stage = pypar.receive(self.inlet_master_proc[self.inflow_index])
                old_inflow_xmom = pypar.receive(self.inlet_master_proc[self.inflow_index])
                old_inflow_ymom = pypar.receive(self.inlet_master_proc[self.inflow_index])
                inflow_area = pypar.receive(self.inlet_master_proc[self.inflow_index])
        elif self.myid == self.inlet_master_proc[self.inflow_index]:
            pypar.send(old_inflow_depth, self.master_proc)
            pypar.send(old_inflow_stage, self.master_proc)
            pypar.send(old_inflow_xmom, self.master_proc)
            pypar.send(old_inflow_ymom, self.master_proc)
            pypar.send(inflow_area, self.master_proc)

        # Implement the update of flow over a timestep by
        # using a semi-implict update. This ensures that
        # the update does not create a negative depth
        
        # Master proc of structure only
        if self.myid == self.master_proc:
            if old_inflow_depth > 0.0 :
                Q_star = Q/old_inflow_depth
            else:
                Q_star = 0.0

            factor = 1.0/(1.0 + Q_star*timestep/inflow_area)

            new_inflow_depth = old_inflow_depth*factor
            new_inflow_xmom = old_inflow_xmom*factor
            new_inflow_ymom = old_inflow_ymom*factor

        # Master proc of structure sends new inflow attributes to all inflow inlet processors

        if self.myid == self.master_proc:
            for i in self.inlet_procs[self.inflow_index]:
                if i == self.master_proc: continue
                pypar.send(new_inflow_depth, i)
                pypar.send(new_inflow_xmom, i)
                pypar.send(new_inflow_ymom, i)
        elif self.myid in self.inlet_procs[self.inflow_index]:
            new_inflow_depth = pypar.receive(self.master_proc)
            new_inflow_xmom = pypar.receive(self.master_proc)
            new_inflow_ymom = pypar.receive(self.master_proc)

        # Inflow inlet procs sets new attributes
        if self.myid in self.inlet_procs[self.inflow_index]:
            self.inlets[self.inflow_index].set_depths(new_inflow_depth)
            self.inlets[self.inflow_index].set_xmoms(new_inflow_xmom)
            self.inlets[self.inflow_index].set_ymoms(new_inflow_ymom)

        # Get outflow inlet attributes, all processors associated with outflow inlet must call
        if self.myid in self.inlet_procs[self.outflow_index]:
            outflow_area = self.inlets[self.outflow_index].get_global_area()
            outflow_average_depth = self.inlets[self.outflow_index].get_global_average_depth()
            outflow_outward_culvert_vector = self.inlets[self.outflow_index].outward_culvert_vector

        # Master proc of outflow inlet sends attribute to master proc of structure
        if self.myid == self.master_proc:
            if self.myid != self.inlet_master_proc[self.outflow_index]:
                outflow_area = pypar.receive(self.inlet_master_proc[self.outflow_index])
                outflow_average_depth = pypar.receive(self.inlet_master_proc[self.outflow_index])
                outflow_outward_culvert_vector = pypar.receive(self.inlet_master_proc[self.outflow_index])
        elif self.myid == self.inlet_master_proc[self.outflow_index]:
            pypar.send(outflow_area, self.master_proc)
            pypar.send(outflow_average_depth, self.master_proc)
            pypar.send(outflow_outward_culvert_vector, self.master_proc)

        # Master proc of structure computes new outflow attributes
        if self.myid == self.master_proc:
            loss = (old_inflow_depth - new_inflow_depth)*inflow_area

            # set outflow
            if old_inflow_depth > 0.0 :
                timestep_star = timestep*new_inflow_depth/old_inflow_depth
            else:
                timestep_star = 0.0

            outflow_extra_depth = Q*timestep_star/outflow_area
            outflow_direction = - outflow_outward_culvert_vector
            outflow_extra_momentum = outflow_extra_depth*barrel_speed*outflow_direction
            
            gain = outflow_extra_depth*outflow_area

        # Update Stats
            self.discharge  = Q#outflow_extra_depth*self.outflow.get_area()/timestep
            self.velocity = barrel_speed#self.discharge/outlet_depth/self.width

            new_outflow_depth = outflow_average_depth + outflow_extra_depth

            if self.use_momentum_jet :
                # FIXME (SR) Review momentum to account for possible hydraulic jumps at outlet
                #new_outflow_xmom = outflow.get_average_xmom() + outflow_extra_momentum[0]
                #new_outflow_ymom = outflow.get_average_ymom() + outflow_extra_momentum[1]

                new_outflow_xmom = barrel_speed*new_outflow_depth*outflow_direction[0]
                new_outflow_ymom = barrel_speed*new_outflow_depth*outflow_direction[1]

            else:
                #new_outflow_xmom = outflow.get_average_xmom()
                #new_outflow_ymom = outflow.get_average_ymom()

                new_outflow_xmom = 0.0
                new_outflow_ymom = 0.0

            # master proc of structure sends outflow attributes to all outflow procs
            for i in self.inlet_procs[self.outflow_index]:
                if i == self.myid: continue
                pypar.send(new_outflow_depth, i)
                pypar.send(new_outflow_xmom, i)
                pypar.send(new_outflow_ymom, i)
        # outflow inlet procs receives new outflow attributes
        elif self.myid in self.inlet_procs[self.outflow_index]:
            new_outflow_depth = pypar.receive(self.master_proc)
            new_outflow_xmom = pypar.receive(self.master_proc)
            new_outflow_ymom = pypar.receive(self.master_proc)

        # outflow inlet procs sets new outflow attributes
        if self.myid in self.inlet_procs[self.outflow_index]:
            self.inlets[self.outflow_index].set_depths(new_outflow_depth)
            self.inlets[self.outflow_index].set_xmoms(new_outflow_xmom)
            self.inlets[self.outflow_index].set_ymoms(new_outflow_ymom)

    def __process_non_skew_culvert(self):
        """Create lines at the end of a culvert inlet and outlet.
        At either end two lines will be created; one for the actual flow to pass through and one a little further away
        for enquiring the total energy at both ends of the culvert and transferring flow.
        """
        
        self.culvert_vector = self.end_points[1] - self.end_points[0]
        self.culvert_length = math.sqrt(num.sum(self.culvert_vector**2))   
        assert self.culvert_length > 0.0, 'The length of culvert is less than 0'
        
        self.culvert_vector /= self.culvert_length
        
        culvert_normal = num.array([-self.culvert_vector[1], self.culvert_vector[0]])  # Normal vector
        w = 0.5*self.width*culvert_normal # Perpendicular vector of 1/2 width

        self.exchange_lines = []

        # Build exchange polyline and enquiry point
        if self.enquiry_points is None:
            
            gap = (self.apron + self.enquiry_gap)*self.culvert_vector
            self.enquiry_points = []
            
            for i in [0, 1]:
                p0 = self.end_points[i] + w
                p1 = self.end_points[i] - w
                self.exchange_lines.append(num.array([p0, p1]))
                ep = self.end_points[i] + (2*i - 1)*gap #(2*i - 1) determines the sign of the points
                self.enquiry_points.append(ep)
            
        else:            
            for i in [0, 1]:
                p0 = self.end_points[i] + w
                p1 = self.end_points[i] - w
                self.exchange_lines.append(num.array([p0, p1]))
            
  
    def __process_skew_culvert(self):    
        
        """Compute skew culvert.
        If exchange lines are given, the enquiry points are determined. This is for enquiring 
        the total energy at both ends of the culvert and transferring flow.
        """
            
        centre_point0 = 0.5*(self.exchange_lines[0][0] + self.exchange_lines[0][1])
        centre_point1 = 0.5*(self.exchange_lines[1][0] + self.exchange_lines[1][1])
        
        if self.end_points is None:
            self.culvert_vector = centre_point1 - centre_point0
        else:
            self.culvert_vector = self.end_points[1] - self.end_points[0]
        
        self.culvert_length = math.sqrt(num.sum(self.culvert_vector**2))
        assert self.culvert_length > 0.0, 'The length of culvert is less than 0'
        
        if self.enquiry_points is None:
        
            self.culvert_vector /= self.culvert_length
            gap = (self.apron + self.enquiry_gap)*self.culvert_vector
        
            self.enquiry_points = []

            self.enquiry_points.append(centre_point0 - gap)
            self.enquiry_points.append(centre_point1 + gap)
            

    def discharge_routine(self):

        msg = 'Need to impelement '
        raise
            

    def statistics(self):
        # Warning: requires synchronization, must be called by all procs associated
        # with this structure

        message = ' '

        if self.myid == self.master_proc:

            message  = '===============================================\n'
            message += 'Parallel Structure Operator: %s\n' % self.label
            message += '===============================================\n'

            message += 'Structure Type: %s\n' % self.structure_type

            message += 'Description\n'
            message += '%s' % self.description
            message += '\n'
        
        for i, inlet in enumerate(self.inlets):
            if self.myid == self.master_proc:
                message += '-------------------------------------\n'
                message +=  'Inlet %i\n' %(i)
                message += '-------------------------------------\n'

            if inlet is not None: stats = inlet.statistics()

            if self.myid == self.master_proc:
                if self.myid != self.inlet_master_proc[i]:
                    stats = pypar.receive(self.inlet_master_proc[i])                    
            elif self.myid == self.inlet_master_proc[i]:
                pypar.send(stats, self.master_proc)

            if self.myid == self.master_proc: message += stats
 

        if self.myid == self.master_proc: message += '=====================================\n'

        return message


    def print_statistics(self):
        # Warning: requires synchronization, must be called by all procs associated
        # with this structure

        print self.statistics()


    def print_timestepping_statistics(self):
        # Warning: must be called by the master proc of this structure to obtain 
        # meaningful output

        message = ' '

        if self.myid == self.master_proc:
            message = '--------------------------------------------------\n'
            message += 'Parallel Structure report for %s:\n' % self.label
            message += '-------------------------------------------------\n'
            message += 'Type: %s\n' % self.structure_type
            message += 'Discharge [m^3/s]: %.2f\n' % self.discharge
            message += 'Velocity  [m/s]: %.2f\n' % self.velocity
            message += 'Inlet Driving Energy %.2f\n' % self.driving_energy
            message += 'Delta Total Energy %.2f\n' % self.delta_total_energy
            message += 'Control at this instant: %s\n' % self.case

        print message


    def set_parallel_logging(self, flag=True):
        # Warning: requires synchronization, must be called by all procs associated
        # with this structure

        stats = self.statistics()
        self.logging = flag

        # If flag is true open file with mode = "w" to form a clean file for logging
        if self.logging and self.myid == self.master_proc:
            self.log_filename = self.label + '.log'
            log_to_file(self.log_filename, stats, mode='w')
            log_to_file(self.log_filename, 'time,discharge,velocity,driving_energy,delta_total_energy')

            #log_to_file(self.log_filename, self.culvert_type)

    def set_logging(self, flag=True):
        # Overwrite the sequential procedure with a dummy procedure.
        # Need to call set_parallel_logging which needs to be done later
        # after the calculation of master processors

        pass


    def log_timestepping_statistics(self):

        from anuga.utilities.system_tools import log_to_file
        if self.logging and self.myid == self.master_proc:
            log_to_file(self.log_filename, self.timestepping_statistics())



    def timestepping_statistics(self):

        message  = '%.5f, ' % self.domain.get_time()
        message += '%.5f, ' % self.discharge
        message += '%.5f, ' % self.velocity
        message += '%.5f, ' % self.driving_energy
        message += '%.5f' % self.delta_total_energy

        return message


    def get_inlets(self):
        
        return self.inlets
        
        
    def get_culvert_length(self):
        
        return self.culvert_length
        
        
    def get_culvert_width(self):        
        return self.width
        
        
    def get_culvert_diameter(self):
        return self.width
        
        
    def get_culvert_height(self):
        return self.height


    def get_culvert_apron(self):
        return self.apron

    # Get id of master proc of this structure
    def get_master_proc(self):
        return self.master_proc

    # Get id of master proc of first and second inlet
    def get_inlet_master_proc(self):
        return self.inlet_master_proc

    # Get id of processors associated with first and second inlet enquiry points
    def get_enquiry_proc(self):
        return self.enquiry_proc


    def parallel_safe(self):
        return True



