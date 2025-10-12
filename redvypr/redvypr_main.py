import ast
import os
import re
import logging
import sys
from PyQt6 import QtWidgets, QtCore, QtGui
import multiprocessing
import argparse
import signal
# Import redvypr specific stuff
import redvypr
import redvypr.files as files
from redvypr import merge_configuration
from redvypr.redvypr_main_widget import redvyprMainWidget
import faulthandler

logfile = None

if sys.stderr is not None:
    #normal mode
    faulthandler.enable()
else:
    # no-console, log to file
    log_path = os.path.join(os.path.dirname(sys.executable), "faulthandler.log")
    logfile = open(log_path, "w")
    faulthandler.enable(file=logfile)

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.redvypr_main')
logger.setLevel(logging.INFO)


redvypr_icon_v02_ascii=r"""
                                        .                       
                                       ..                       
        ..                            .,'                       
         ''.                         .,,,.                      
          ',,'.                     .,,,,.                      
           .,,,,..    .'''..........,,,,,,                      
            .,,,,,,..',,,,,,,,,,,,,,,,,,,,.                     
             .,,,,,,,,,,,,,,,,,,,,,,,,,,,,'                     
              ',,,,,,,,,,,,,,,,,,,,,,,,,,,,.  ..                
              .,,,,,,,,,,,,,,,,,,,,,,,,,,,,,'. dW0              
               ',,,,,,,,,,,,,,,,,,,,,,,,,,,,,,. :W.x:           
               .,,,,,,,'....',,,,,,,,,,,,,,,,,,'.. KM:          
               .,,,,,'. lkO;  .,,,,,,,,,,,,,,,,,,. lWX          
               ',,,,,. xMMO.kO .,,,,,,,,,,,,,,,,,,'..;          
               ,,,,,' ,MMk.0MMx ,,,,,,,,,,,,,,,,,,,,'..         
              ',,,,,, :MK kMMMx ,,,,,,,,,,,,,,,,,,,,,,,'        
             .,,,,,,,. kl MMMO .,,,,,,,,,,,,,,,,,,,,,,,,,.      
             .,,,,,,,,.  .dx: .,,,'',,,,,,,,,,,,,,,,,,,,,,'     
            .,,,,,,,,,,,'....',,,,. ,,,,,,,,,,,,,,,,,,,,,,,.    
            ',,,,,,,,,,,,,,,,,,,,,. ,,,,,,,,,,,,,,,,,,,,,,,.    
           .,,,,,,,,,,,,,,,,,,,,,,. .',,,,,,,,,,,,,,,,,,,,'     
           ,,,,,,,,,,,,,,,,,,,,,,,,......',,,,,,,,,,,,,,'.      
          ',,,,,,,,,,,,,,,,,,,,,,,,,,,'..  ...''',,,..          
         ',,,,,,,,,,,,,,,,,,,,,,,,,,,,,,'..      ..,'.          
        .,,,,,,,,,,,,,,,,,,,,,,,,,,,'..            .','.        
       .,,,,,,,,,,,,,,,,,,,,,,,,'..                  .',.       
      .,,,,,,,,,,,,,,,,,,,,,,,'.                       .,.      
    .',,,,,,,,,,,,,,,,,,,,,,.                           ',      
   ',,,,,,,,,,,,,,,,,,,,,,'                             .,'     
 .,,,,,,,,,,,,,,,,,,,,,,,'                              .,''.   
,,,,,,,,,,,,,,,,,,,,,,,,'                               ..   .  
,,,,,,,,,,,,,,,,,,,,,,,,                                .       
,,,,,,,,,,,,,,,,,,,,,,,.                                        
,,,,,,,,,,,,,,,,,,,,,,'
"""

redvypr_figlet=r"""
              _
 _ __ ___  __| |_   ___   _ _ __  _ __
| '__/ _ \/ _` \ \ / / | | | '_ \| '__|
| | |  __/ (_| |\ V /| |_| | |_) | |
|_|  \___|\__,_| \_/  \__, | .__/|_|
                      |___/|_|
                      
"""


# Windows icon fix
# https://stackoverflow.com/questions/1551605/how-to-set-applications-taskbar-icon-in-windows-7/1552105#1552105
import ctypes
myappid = u'redvypr.redvypr.version'  # arbitrary string
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except:
    pass

_logo_file = files.logo_file
_icon_file = files.icon_file


def split_quotedstring(qstr, separator=','):
    """ Splits a string
    """
    r = re.compile("'.+?'")  # Single quoted string

    d = qstr[:]
    quoted_list = r.findall(d)
    quoted_dict = {}
    for fstr in quoted_list:
        u1 = uuid.uuid4()
        d = d.replace(fstr, u1.hex, 1)
        quoted_dict[u1.hex] = fstr

    ds = d.split(separator)
    for i, dpart in enumerate(ds):
        for k in quoted_dict.keys():
            dpart = dpart.replace(k, quoted_dict[k])
            ds[i] = dpart

    return ds

#
#
# Main function called from os
#
#
#
def redvypr_main():
    if True:
        print(redvypr_icon_v02_ascii)
        print(redvypr_figlet)

    redvypr_help = 'redvypr'
    config_help_verbose = 'verbosity, if argument is called at least once loglevel=DEBUG, otherwise loglevel=INFO'
    config_help = 'Using a yaml config file'
    config_help_nogui = 'start redvypr without a gui'
    config_help_path = 'add path to search for redvypr modules'
    config_help_hostname = 'hostname of redvypr, overwrites the hostname in a possible configuration '
    add_device_example = '\t-a test_device, s, [mp / th], loglevel: [DEBUG / INFO / WARNING], name: test_1, subscribe: "*"'
    add_device_example_2 = ', also device specific configuration can be set similarly: -a test_device,delay_s: 0.4, '
    config_help_add = 'add device, can be called multiple times, optional options/configuration can be added by comma separated input:' + add_device_example + add_device_example_2
    config_help_list = 'lists all known devices'
    config_optional = 'optional information about the redvypr instance, multiple calls possible or separated by ",". Given as a key:data pair: --hostinfo location:lab --hostinfo lat:10.2,lon:30.4. The data is tried to be converted to an int, if that is not working as a float, if that is neither working at is passed as string'
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', '-v', action='count', help=config_help_verbose)
    parser.add_argument('--config', '-c', help=config_help)
    parser.add_argument('--nogui', '-ng', help=config_help_nogui, action='store_true')
    parser.add_argument('--add_path', '-p', help=config_help_path)
    parser.add_argument('--hostname', '-hn', help=config_help_hostname)
    parser.add_argument('--metadata', '-m', help=config_optional, action='append')
    parser.add_argument('--add_device', '-a', help=config_help_add, action='append')
    parser.add_argument('--list_devices', '-l', help=config_help_list, action='store_true')
    parser.set_defaults(nogui=False)
    args = parser.parse_args()

    # Check if list devices only
    if (args.list_devices):
        # Set the nogui flag
        args.nogui = True

    logging_level = logging.INFO
    if (args.verbose == None):
        logging_level = logging.INFO
        loglevel_redvypr=None
    elif (args.verbose >= 1):
        print('Debug logging level')
        logging_level = logging.DEBUG
        loglevel_redvypr = 'DEBUG'

    logger.setLevel(logging_level)

    # Check if we have a redvypr.yaml, TODO, add also default path
    config_all = [] # Make a config all, the list can have several dictionaries that will be all processed by the redvypr initialization
    if (os.path.exists('redvypr.yaml')):
        config_all.append('redvypr.yaml')

    # Adding device module pathes
    if (args.add_path is not None):
        # print('devicepath',args.add_path)
        modpath = os.path.abspath(args.add_path)
        # print('devicepath',args.add_path,modpath)
        # print('Modpath',modpath)
        config_add = redvypr.RedvyprConfig(devicepaths=[modpath])
        config_all.append(config_add)

    # Add the configuration
    config = args.config
    if (config is not None):
        config_all.append(config)

    # Add device
    if (args.add_device is not None):
        devices_add = []
        #print('devices!', args.add_device)
        for d in args.add_device:
            deviceconfig = redvypr.RedvyprDeviceConfig().model_dump()
            deviceconfig['custom_config'] = {} # Change the None manually to a dictionary
            #deviceconfig = {'base_config':{},'config':{},'subscriptions':[]}
            #deviceconfig['base_config'] = {'autostart':False,'loglevel':logging_level,'multiprocess':'qthread'}
            if(',' in d):
                logger.debug('Found options')
                #devicemodulename = d.split(',')[0]
                #options = d.split(',')[1:]
                # Split the string, using csv reader to have quoted strings conserved
                options_all = split_quotedstring(d)
                #print('options all',options_all)
                devicemodulename = options_all[0]
                options = options_all[1:]
                #print('options', options,type(options))
                for indo,option in enumerate(options):
                    #print('Option',option,len(option),indo)
                    if(option == 's'):
                        print('Autostart')
                        deviceconfig['base_config']['autostart'] = True
                    elif (option == 'mp' or option == 'multiprocess') and (':' not in option):
                        deviceconfig['base_config']['multiprocess'] = 'multiprocess'
                    elif (option == 'th' or option == 'thread') and (':' not in option):
                        deviceconfig['base_config']['multiprocess'] = 'qthread'
                    elif (':' in option):
                        key = option.split(':')[0]
                        data = option.split(':')[1]
                        #print('data before',data,key)
                        if (data[0] == "'") and (data[-1] == "'"):
                            try:
                                data = ast.literal_eval(data[1:-1])
                            except Exception as e:
                                logger.info('Error parsing options:', exc_info=True)
                        else:
                            try:
                                data = int(data)
                            except:
                                try:
                                    data = float(data)
                                except:
                                    pass

                        #print('Data', data)
                        #print('type Data', type(data))
                        #print('Data', data)
                        #print('key', key)
                        if(key == 'name'):
                            deviceconfig['base_config'][key] = data
                        elif (key == 'loglevel') or (key == 'll'):
                            try:
                                loglevel_tmp = data
                                loglevel_device = getattr(logging, loglevel_tmp.upper())
                            except Exception as e:
                                print(e)
                                loglevel_tmp = 'INFO'
                                loglevel_device = getattr(logging, loglevel_tmp.upper())

                            print('Setting device {:s} to loglevel {:s}'.format(devicemodulename,loglevel_tmp))
                            deviceconfig['base_config']['loglevel'] = loglevel_device
                        elif (key.lower() == 'subscribe'):
                            print('Add subscription {}'.format(str(data)))
                            deviceconfig['subscriptions'].append(data)
                        else:
                            print('Adding key',key,data)
                            deviceconfig['custom_config'][key] = data
            else:
                devicemodulename = d

            deviceconfig['devicemodulename'] = devicemodulename
            devconfig = redvypr.RedvyprDeviceConfig(**deviceconfig)
            devices_add.append(devconfig)
            logger.info('Adding device {}'.format(d))

        config_devices = redvypr.RedvyprConfig(devices=devices_add)
        #print('Devices to add')
        #print('D',config_devices)
        #print('Done')
        config_all.append(config_devices)

    # Add hostname
    if (args.hostname is not None):
        hostname = args.hostname
    else:
        hostname = 'redvypr'

    # Add metadata
    if (args.metadata is not None):
        metadata = args.metadata
        # Add optional metadata
        metadata_tmp = {}
        for i in metadata:
            for info in i.split(','):
                #print('Info',info)
                if(':' in info):
                    key = info.split(':')[0]
                    data = info.split(':')[1]
                    try:
                        data = int(data)
                    except:
                        try:
                            data = float(data)
                        except:
                            pass

                    metadata_tmp[key] = data
                else:
                    logger.warning('Not a key:data pair in metadata, skipping {:sf}'.format(info))

        metadata_obj = redvypr.RedvyprMetadata(**metadata_tmp)
        config_metadata = redvypr.RedvyprConfig(metadata=metadata_obj)
        config_all.append(config_metadata)

    #print('Config all',config_all)
    config = merge_configuration(config_all)
    #print('Config',config)

    #config_all.append({'hostinfo_opt':hostinfo_opt})
    #print('Hostinfo', hostinfo)
    #print('Hostinfo opt', hostinfo_opt)

    logger.debug('Configuration:\n {:s}\n'.format(str(config_all)))
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
    # GUI oder command line?
    if (args.nogui):
        def handleIntSignal(signum, frame):
            '''Ask app to close if Ctrl+C is pressed.'''
            print('Received CTRL-C: Closing now')
            sys.exit()

        signal.signal(signal.SIGINT, handleIntSignal)
        app = QtCore.QCoreApplication(sys.argv)
        redvypr_obj = redvypr.Redvypr(config=config, hostname=hostname, nogui=True, loglevel=loglevel_redvypr)
        # Check if the devices shall be listed only
        if (args.list_devices):
            devices = redvypr_obj.get_known_devices()
            print('Known devices')
            for d in devices:
                print(d)

            sys.exit()
        sys.exit(app.exec_())
    else:
        app = QtWidgets.QApplication(sys.argv)
        app.setWindowIcon(QtGui.QIcon(_icon_file))
        screen = app.primaryScreen()
        # print('Screen: %s' % screen.name())
        size = screen.size()
        # print('Size: %d x %d' % (size.width(), size.height()))
        rect = screen.availableGeometry()
        width = int(rect.width() * 4 / 5)
        height = int(rect.height() * 2 / 3)

        logger.debug(
            'Available screen size: {:d} x {:d} using {:d} x {:d}'.format(rect.width(), rect.height(), width, height))
        ex = redvyprMainWidget(width=width, height=height, config=config, hostname=hostname, loglevel=loglevel_redvypr)

        sys.exit(app.exec_())


if __name__ == '__main__':
    #https://stackoverflow.com/questions/46335842/python-multiprocessing-throws-error-with-argparse-and-pyinstaller
    multiprocessing.freeze_support()
    redvypr_main()