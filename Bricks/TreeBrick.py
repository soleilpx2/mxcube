import traceback
import queue_item
import queue_model
import logging
import sys
import time
import os

from BlissFramework import Icons
from BlissFramework.Utils import widget_colors
from widgets.dc_tree_widget import DataCollectTree
from widgets.dc_tree_widget import SC_FILTER_OPTIONS
from widgets.sample_changer_widget_layout import SampleChangerWidgetLayout
from collections import namedtuple
from BlissFramework import BaseComponents
from BlissFramework import Icons
from qt import *


__category__ = 'mxCuBE_v3'


ViewType = namedtuple('ViewType', ['ISPYB', 'MANUAL', 'SC'])
TREE_VIEW_TYPE = ViewType(0, 1, 2)


class TreeBrick(BaseComponents.BlissWidget):
    def __init__(self, *args):
        BaseComponents.BlissWidget.__init__(self, *args)

        # Internal members
        self.current_cpos = None
        self.__collection_stopped = False 
        self.current_view = None
        self.ispyb_logged_in = False

        # Framework 2 hardware objects
        self.collect_hwobj = None
        self.beamline_config_hwobj = None
        self.data_analysis_hwobj = None
        self.energy_scan_hwobj = None
        self._lims_hwobj = None
        self.sample_changer = None
        self.queue_hwobj = None
        self.xml_rpc_server_hwobj = None

        # Properties
        self.addProperty("lims_client", "string", "")
        self.addProperty("dataCollect", "string", "")
        self.addProperty("dataAnalysis", "string", "")
        self.addProperty("beamlineConfig", "string", "")
        self.addProperty("sampleChanger", "string", "")
        self.addProperty("diffractometer", "string", "")
        self.addProperty("holderLengthMotor", "string", "")
        self.addProperty("energy_scan_hwobj", "string", "")
        self.addProperty("queue", "string", "/queue-controller")
        self.addProperty("xml_rpc_server", "string", "/xml-rpc-server")

        # Qt - Slots
        self.defineSlot("logged_in", ())
        self.defineSlot("get_tree_brick",())
        self.defineSlot("add_dcg", ())
        self.defineSlot("add_data_collection", ())
        self.defineSlot("set_session", ())
        self.defineSlot("get_selected_samples", ())
        self.defineSlot("get_mounted_sample", ())
        self.defineSlot("new_centred_position", ())

        # From SampleChangerBrick3, signal emitted when
        # the status of the hwobj changes.
        self.defineSlot("status_msg_changed", ())

        # From sample changer hwobj, emitted when the
        # load state changes.
        self.defineSlot("sample_load_state_changed", ())
        
        # Qt - Signals
        self.defineSignal("hide_sample_tab", ())
        self.defineSignal("hide_dc_parameters_tab", ())
        self.defineSignal("hide_sample_centring_tab", ())
        self.defineSignal("hide_dcg_tab", ())
        self.defineSignal("hide_sample_changer_tab", ())
        self.defineSignal("hide_edna_tab", ())
        self.defineSignal("hide_energy_scan_tab",())
        self.defineSignal("populate_parameter_widget", ())
        self.defineSignal("clear_centred_positions", ())
        self.defineSignal("populate_edna_parameter_widget",())
        self.defineSignal("populate_sample_details",())
        self.defineSignal("selection_changed",())
        self.defineSignal("populate_energy_scan_widget", ())

        # Layout
        self.setSizePolicy(QSizePolicy(QSizePolicy.Fixed,
                                       QSizePolicy.Expanding))
                                       
        self.sample_changer_widget = SampleChangerWidgetLayout(self)
        self.refresh_pixmap = Icons.load("Refresh2.png")
        self.sample_changer_widget.synch_button.setPixmap(self.refresh_pixmap)

        self.dc_tree_widget = DataCollectTree(self)
        self.dc_tree_widget.selection_changed_cb = self.selection_changed
        self.dc_tree_widget.run_cb = self.run
        self.dc_tree_widget.clear_centred_positions_cb = \
            self.clear_centred_positions

        QObject.connect(self.sample_changer_widget.details_button, 
                        SIGNAL("clicked()"),
                        self.toggle_sample_changer_tab)

        QObject.connect(self.sample_changer_widget.filter_cbox,
                        SIGNAL("activated(int)"),
                        self.dc_tree_widget.filter_sample_list)

        QObject.connect(self.sample_changer_widget.centring_cbox,
                        SIGNAL("activated(int)"),
                        self.dc_tree_widget.set_centring_method)

        QObject.connect(self.sample_changer_widget.synch_button,
                        SIGNAL("clicked()"),
                        self.refresh_sample_list)

        vlayout = QVBoxLayout(self, 0, 0, 'main_layout')
        vlayout.setSpacing(10)
        self.layout().addWidget(self.sample_changer_widget)
        self.layout().addWidget(self.dc_tree_widget)
        self.enable_collect(self.ispyb_logged_in)


    def refresh_sample_list(self):
        collect_context = queue_model.QueueModelFactory.get_context()
        lims_client = self._lims_hwobj
        samples = lims_client.get_samples(collect_context.prop_id,
                                          collect_context.session_id)
            
        if samples:
            self.dc_tree_widget.init_with_ispyb_data(samples)


    def set_session(self, session_id, t_prop_code = None, prop_number = None,
                    prop_id = None, start_date = None, prop_code = None, is_inhouse = None):

        collect_context = queue_model.QueueModelFactory.get_context()  
        collect_context.session_id = session_id
        collect_context.prop_code = prop_code
        collect_context.prop_id = prop_id
        collect_context.start_date = start_date

        try:
            collect_context.prop_number = int(prop_number)
        except (TypeError, ValueError):
            collect_context.prop_number = 0
        

        # Tried to log into ISPyB but it didnt work for some reason,
        # no valid session.
        if session_id is '':
            logging.getLogger("user_level_log").\
                warning('Could not log into ISPyB, data will not be stored in ISPyB.')
            logging.getLogger("user_level_log").\
                warning('Could not log into ISPyB, using inhouse user to collect data.')
            
            try:
                self._lims_hwobj.disable()
            except:
                logging.warning('Could not disable lims.')
                traceback.print_exc()

            #collect_context.set_inhouse(True)
        else:
            lims_client = self._lims_hwobj
            samples = lims_client.get_samples(prop_id, session_id)
            sc_content = self.get_sc_content()

            #smp = self.dc_tree_widget.crosscheck_sample_lists(sc_content, samples)
            
            if samples:
                self.dc_tree_widget.init_with_ispyb_data(samples)

            
    def logged_in(self, logged_in):
        """
        Connected to the signal loggedIn of ProposalBrick2.
        The signal is emitted when a user was succesfully logged in.
        """
        self.ispyb_logged_in = logged_in
        self.enable_collect(self.ispyb_logged_in)

        if not logged_in:
            sc_content = self.get_sc_content()
            self.dc_tree_widget.init_with_sc_content(sc_content)


    def enable_collect(self, state):
        self.dc_tree_widget.sample_list_view.setDisabled(not state)
        self.dc_tree_widget.collect_button.setDisabled(not state)
        self.dc_tree_widget.up_button.setDisabled(not state)
        self.dc_tree_widget.down_button.setDisabled(not state)
        self.dc_tree_widget.delete_button.setDisabled(not state)


    def get_tree_brick(self, tree_brick):
        tree_brick['tree_brick'] = self


    def propertyChanged(self, property_name, old_value, new_value):
        if property_name == 'dataCollect':
            self.collect_hwobj = self.getHardwareObject(new_value)
            
        if property_name == 'dataAnalysis':
            self.data_analysis_hwobj = self.getHardwareObject(new_value)

        if property_name == 'beamlineConfig':
            self.beamline_config_hwobj = self.getHardwareObject(new_value)
            try:
                collect_context = queue_model.QueueModelFactory.get_context()
                collect_context.beamline_config_hwobj = self.beamline_config_hwobj

                if collect_context.beamline_config_hwobj:
                    collect_context.suffix = self.beamline_config_hwobj["BCM_PARS"].\
                                             getProperty("FileSuffix")

                    collect_context.set_exp_hutch(self.beamline_config_hwobj["BCM_PARS"].\
                                                  getProperty("hutch"))

                    inhouse_proposals = self.beamline_config_hwobj\
                                        ["INHOUSE_USERS"]["proposal"]

                    for prop in inhouse_proposals:
                        collect_context.in_house.append((prop.getProperty('code'),
                                                         prop.getProperty('number')))
            except:
                pass
                


        if property_name == 'sampleChanger':
            self.sample_changer_hwobj = self.getHardwareObject(new_value)
            self.dc_tree_widget.sample_changer_hwobj = self.sample_changer_hwobj

            sc_content = self.get_sc_content()
            self.dc_tree_widget.init_with_sc_content(sc_content)

            if self.sample_changer_hwobj:
                self.connect(self.sample_changer_hwobj, 'sampleIsLoaded',
                             self.sample_load_state_changed)


        if property_name == 'diffractometer':
            self.diffractometer_hwobj = self.getHardwareObject(new_value)

            if self.diffractometer_hwobj:
                self.dc_tree_widget.diffractometer_hwobj = self.getHardwareObject(new_value)

        
        if property_name == 'holder_length_motor':
            self.dc_tree_widget.hl_motor_hwobj = self.getHardwareObject(new_value)


        if property_name == 'lims_client':
            self._lims_hwobj = self.getHardwareObject(new_value)


        if property_name == 'energy_scan_hwobj':
            self.energy_scan_hwobj = self.getHardwareObject(new_value)


        if property_name == 'queue':
            self.queue_hwobj = self.getHardwareObject(new_value)
            self.dc_tree_widget.queue_hwobj = self.queue_hwobj


        if property_name == 'xml_rpc_server':
            self.xml_rpc_server_hwobj = self.getHardwareObject(new_value)
            self.connect(self.xml_rpc_server_hwobj, 'add_to_queue',
                         self.add_to_queue)

            self.connect(self.xml_rpc_server_hwobj, 'start_queue',
                         self.dc_tree_widget.collect_items)


    def get_sc_content(self):
        sc_content = []
        
        try:
            sc_content = self.sample_changer_hwobj.getMatrixCodes()            
        except Exception as ex:
            logging.getLogger("user_level_log").\
                info("Could not connect to sample changer,"  + \
                     " unable to list contents. Make sure that" + \
                     " the sample changer is turned on. Using free pin mode")
            sc_content = [('', -1, -1, '', 1)]
            self.dc_tree_widget.init_with_sc_content(sc_content)
            self.dc_tree_widget.filter_sample_list(SC_FILTER_OPTIONS.FREE_PIN)
            self.sample_changer_widget.filter_cbox.\
                setCurrentItem(SC_FILTER_OPTIONS.FREE_PIN)

        return sc_content


    def clear_centred_positions(self):
        self.emit(PYSIGNAL("clear_centred_positions"), (None,))


    def status_msg_changed(self, msg, color):
        logging.getLogger("user_level_log").info(msg)


    def sample_load_state_changed(self, state):
        self.dc_tree_widget.sample_load_state_changed(state)


    def set_holder_length(self, position):
        self._holder_length = position

    
    def show_sample_centring_tab(self):
        self.sample_changer_widget.details_button.setText("Show details")
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_centring_tab"), (False,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,))


    def show_sample_tab(self, item):
        self.sample_changer_widget.details_button.setText("Show details")
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("populate_sample_details"), (item.get_model(),))
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_centring_tab"), (False,))
        self.emit(PYSIGNAL("hide_sample_tab"), (False,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,))


    def show_dcg_tab(self):
        self.sample_changer_widget.details_button.setText("Show details")
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("hide_dcg_tab"), (False,))
        #self.emit(PYSIGNAL("hide_sample_centring_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,))


    def populate_parameters_tab(self, item = None):
        self.emit(PYSIGNAL("populate_parameter_widget"),
                  (item.get_model(),))
        

    def show_datacollection_tab(self, item):
        self.sample_changer_widget.details_button.setText("Show details")
        #self.emit(PYSIGNAL("hide_sample_centring_tab"), (True,))
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (False,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,))
        self.populate_parameters_tab(item)


    def show_edna_tab(self, item):
        self.sample_changer_widget.details_button.setText("Show details")
        #self.emit(PYSIGNAL("hide_sample_centring_tab"), (True,))
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (False,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,)) 
        self.populate_edna_parameters_tab(item)


    def populate_edna_parameters_tab(self, item):
        self.emit(PYSIGNAL("populate_edna_parameter_widget"),
                  (item.get_model(),))


    def show_energy_scan_tab(self, item):
        self.sample_changer_widget.details_button.setText("Show details")
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,)) 
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (False,)) 
        self.populate_energy_scan_tab(item)


    def populate_energy_scan_tab(self, item):
        self.emit(PYSIGNAL("populate_energy_scan_widget"), (item.get_model(),))
        

    def toggle_sample_changer_tab(self): 
        if self.current_view is self.sample_changer_widget:
            self.current_view = None
            self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
            self.dc_tree_widget.sample_list_view_selection()
            self.sample_changer_widget.details_button.setText("Show details")

        else:
            self.current_view = self.sample_changer_widget
            self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
            self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
            #self.emit(PYSIGNAL("hide_sample_centring_tab"), (True,))
            self.emit(PYSIGNAL("hide_sample_changer_tab"), (False,))
            self.sample_changer_widget.details_button.setText("Hide details")
            self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        

    def selection_changed(self, items):
        if len(items) == 1:
            item = items[0]
            if isinstance(item, queue_item.SampleQueueItem):
                self.emit(PYSIGNAL("populate_sample_details"), (item.get_model(),))
            elif isinstance(item, queue_item.DataCollectionQueueItem):
                self.populate_parameters_tab(item)
            elif isinstance(item, queue_item.CharacterisationQueueItem):
                self.populate_edna_parameters_tab(item)

        self.emit(PYSIGNAL("selection_changed"), (items,))


    def new_centred_positions(self, state, centring_status):
        p_dict = {}
        
        if 'motors' in centring_status and \
                'extraMotors' in centring_status:

            p_dict = dict(centring_status['motors'], 
                          **centring_status['extraMotors'])

        elif 'motors' in centring_status:
            p_dict = dict(centring_status['motors']) 

        if p_dict:
            cpos = queue_model.CentredPosition(p_dict)

        self.current_cpos = cpos


        

    def get_selected_items(self):
        items = self.dc_tree_widget.get_selected_items()
        return items


    def get_selected_samples(self):
        sample_items = self.dc_tree_widget.get_selected_samples()
        return sample_items


    def get_selected_groups(self):
        return self.dc_tree_widget.get_selected_dcgs()

            
    # def get_mounted_sample_item(self, s):
    #     sample_item = self.dc_tree_widget.get_mounted_sample()
    #     s['sample'] = sample_item.get_model()
    

    # def is_sample_selected(self, selected_sample_dict):
    #     selected_sample = self.dc_tree_widget.is_sample_selected()

    #     if selected_sample:        
    #         selected_sample_dict["sample_selected"] = True
    #     else:
    #         selected_sample_dict["sample_selected"] = False


    def add_to_queue(self, task_list, parent_tree_item = None, set_on = True):
        if not parent_tree_item :
            parent_tree_item = self.dc_tree_widget.get_mounted_sample_item()
        
        self.dc_tree_widget.add_to_queue(task_list, parent_tree_item, set_on)


    def run(self):
        self.emit(PYSIGNAL("hide_dc_parameters_tab"), (True,))
        self.emit(PYSIGNAL("hide_dcg_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_centring_tab"), (False,))
        self.emit(PYSIGNAL("hide_edna_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_changer_tab"), (True,))
        self.emit(PYSIGNAL("hide_sample_tab"), (True,))
        self.emit(PYSIGNAL("hide_energy_scan_tab"), (True,))
        self.dc_tree_widget.sample_list_view_selection()

        self.connect(self.queue_hwobj, 'queue_paused', 
                     self.dc_tree_widget.queue_paused_handler)

        self.connect(self.queue_hwobj, 'queue_execution_finished', 
                     self.dc_tree_widget.queue_execution_completed)

        self.connect(self.queue_hwobj, 'queue_stopped', 
                     self.dc_tree_widget.queue_stop_handler)


def get_sample_changer_data() :
    sc_data = [('#ABCDEF12345', 1, 1, '', 16),
               ('#ABCDEF12345', 1, 2, '', 1),
               ('#ABCDEF12345', 1, 3, '', 1),
               ('#ABCDEF12345', 1, 4, '', 1),
               ('#ABCDEF12345', 1, 5, '', 1),
               ('#ABCDEF12345', 1, 6, '', 1),
               ('#ABCDEF12345', 1, 7, '', 1),
               ('#ABCDEF12345', 1, 8, '', 1),
               ('#ABCDEF12345', 1, 9, '', 1),
               ('#ABCDEF12345', 1, 10, '', 1),
               ('#ABCDEF12345', 5, 10, '', 1)]

    return sc_data


def get_sample_data():
    sc_data = [('Current sample', '0:0', '', 16)]
    return sc_data