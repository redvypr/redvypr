import yaml
import re
import pkg_resources
import os
import logging
import sys
import copy
import io
from importlib import import_module
import inspect
from . import NMEA_functions

# Setup logging module
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
logger = logging.getLogger('csv2dict')

version='0.0.1'

csvdefinitions = []

try:
    NMEA_file = pkg_resources.resource_filename('redvypr', 'utils/csv2dict/NMEA.yaml')
except:
    NMEA_file = None
if NMEA_file is not None:
    NMEA_f = open(NMEA_file)
    NMEA_definitions = yaml.load(NMEA_f, Loader=yaml.SafeLoader)
    NMEA_f.close()
    csvdefinitions.extend(NMEA_definitions)


postprocessmodules = [NMEA_functions] # A list of postprocessmodules



def rawcopy(data):
    """
    Functions that simply returns the input data, used as the basic field conversion function
    """
    return data

def NMEA_latstr(nmeastr):
    """
    Parses a NMEA latitude/longitude string and returns a float with the latitude or longitude
    """
    lat = float(nmeastr[0:2]) + float(nmeastr[2:])/60
    return lat

def NMEA_lonstr(nmeastr):
    """
    Parses a NMEA latitude/longitude string and returns a float with the latitude or longitude
    """
    lon = float(nmeastr[0:3]) + float(nmeastr[3:])/60
    return lon


class csv2dict():
    """

    """
    def __init__(self,newline='\n',dict_per_line = True):
        """

        """
        funcname = __name__ + '__init__()'
        logger.debug(funcname + ': version: {:s}'.format(version))
        self.csvdefinitions = []
        self.templatedictslist = []
        self.templatedictsdict = {}
        self.dict_per_line     = dict_per_line
        self.newline           = newline

    def add_standard_csvdefinitions(self):
        """
        Adds standard definitions that come shipped with csv2dict
        """
        funcname = __name__ + 'add_standard_csvdefinitions()'
        logger.debug(funcname)
        self.add_csvdefinition(csvdefinitions)

    def create_templatedict(self,csvdefinition):
        """
        Create a template dictionary for the csvdefintion, that will be filled and returned after parsing the data
        """
        csvdict = {}
        csvdict['name'] = csvdefinition['name']
        for i,fieldname in enumerate(csvdefinition['fieldname']):
            csvdict[fieldname] = []

        return csvdict


    def add_csvdefinition(self,csvdefinitions):
        """

        """
        # Copy the definition first, as it will be modified
        csvdefinitions_copy = copy.deepcopy(csvdefinitions)
        for csvdef in csvdefinitions_copy:
            # Create a template dictionary for ech definition
            csvdict = self.create_templatedict(csvdef)
            self.templatedictslist.append(csvdict)
            name = csvdict['name']
            self.templatedictsdict[name] = csvdict
            # Add the definition
            self.csvdefinitions.append(csvdef)
            # Add conversion functions to csvdefinition
            csvdef['fieldfunction'] = []
            #
            for i in range(len(csvdef['fieldname'])):
                csvdef['fieldfunction'].append(rawcopy)

            # TODO check for modules to be imported
            # Check for postprocessing function
            csvdef['postprocess_func'] = None
            try:
                postfunc = csvdef['postprocess']
                # TODO, this should be a search function option
                for pmod in postprocessmodules:
                    device_module_tmp = inspect.getmembers(pmod, inspect.isfunction)
                    for func_tmp in device_module_tmp:
                        func_name_tmp = func_tmp[0]
                        if(func_name_tmp == postfunc):
                            print('Found function')
                            csvdef['postprocess_func'] = func_tmp[1]

            except Exception as e:
                logger.debug('No postprocessing function found')


            for i,f in enumerate(csvdef['fieldname']):
                try:
                    f = csvdef['fieldformat'][i]
                except:
                    f = 'raw'
                if (f.lower() == 'str'):
                    csvdef['fieldfunction'][i] = str
                elif (f.lower() == 'int'):
                    csvdef['fieldfunction'][i] = int
                elif (f.lower() == 'float'):
                    csvdef['fieldfunction'][i] = float
                elif (f.lower() == 'nmealatstr'):
                    csvdef['fieldfunction'][i] = NMEA_latstr
                elif (f.lower() == 'nmealonstr'):
                    csvdef['fieldfunction'][i] = NMEA_lonstr


    def print_definitions(self):
        """
        Prints all available definitions
        """
        for csvdef in self.csvdefinitions:
            print(csvdef['name'])

    def __create_result_dicts(self):
        """
        Creates an empty dictionary for the parsed results
        """
        result_dicts = {}
        for tdict in self.templatedictslist:
            name = tdict['name']
            result_dicts[name] = copy.deepcopy(tdict)

    def parse_file(self, filename):

            try:
                f = open(filename,'rb')
            except:
                logger.warning('Could not open file {:s}'.format(filename))
                return None

            if True:
                # Create the dictionaries
                result_dicts = self.__create_result_dicts()


            while True:
                lineb = f.readline()
                if len(lineb) == 0:
                    break
                try:
                    line = lineb.decode('utf-8')
                    self.__parse_line(line, result_dicts)
                except:
                    pass

            return result_dicts

    def parse_data(self, data):
        """
        Here a string is parsed, this includes comparing the csvdefinitions with the string and if one found a conversion of the string into a dictionary
        """
        # Create either a list with a dictionary per parsed line or a dictionary with a key entry per parsed csv definition
        if (self.dict_per_line == True):
            result_list = []
            result = result_list
        else:
            result_dicts = {}
            result = result_dicts

        if type(data) == str:
            databuf = io.StringIO(data)
        elif type(data) == bytes:
            databuf = io.StringIO(data.decode('utf-8'))
        else:
            databuf = data

        while True:
            line = databuf.readline()
            if len(line) != 0:
                print('Line',line)
                if self.dict_per_line == True:
                    result_dicts = {}
                    conversion_ok = self.__parse_line(line, result_dicts,dict_per_line=True)
                    if(conversion_ok):
                        key = list(result_dicts.keys())[0] # TODO, this can be done in a smarter way ...
                        result_list.append(result_dicts[key])
                else:
                    self.__parse_line(line, result_dicts,dict_per_line=False)
                continue
            break

        return result

    def __parse_line(self, line, result_dicts,dict_per_line=True):
        """ Loops over all csv definitions and searches for a match
        """
        for indcsv,csvdef in enumerate(self.csvdefinitions):
            deli     = csvdef['delimiter']
            ident    = csvdef['identifier']
            fieldnum = csvdef['identifier_field']
            name     = csvdef['name']
            lsp = line.split(deli) # Split the line
            #print(lsp)
            try:
                lsp_idfield = lsp[fieldnum] # Get the fieldnumber with the id
            except: # If the fieldnumber is not existent continue
                continue

            #print(ident,lsp_idfield)
            FLAG_RESULT = False
            s = re.search(ident,lsp_idfield)
            if(s is not None): # Identifier match, lets start the conversion
                FLAG_RESULT = True
                print('Found correct identifier',ident)
                # loop over all fieldnames
                for i,fieldname in enumerate(csvdef['fieldname']):
                    convfunc = csvdef['fieldfunction'][i]
                    try:
                        #print(lsp[i],convfunc)
                        data = convfunc(lsp[i]) # Convert the data
                    except Exception as e:
                        logger.exception(e)
                        print('Conversion error:',e)
                        print('lsp', lsp)
                        print('i', i)
                        data = None

                    #print('fieldname',fieldname)
                    # create the results dictionary, if it is not existing already
                    try:
                        result_dicts[name]
                    except:
                        result_dicts[name] = copy.deepcopy(self.templatedictsdict[name])

                    if(dict_per_line):
                        result_dicts[name][fieldname] = data
                    else:
                        result_dicts[name][fieldname].append(data)

                # check if a device id is present, if yes add it
                try:
                    deviceid = csvdef['deviceid']
                except:
                    deviceid = None

                if(deviceid is not None):
                    result_dicts[name]['deviceid'] = result_dicts[name][deviceid]

                # Check for a postprocess function, if available call it with the dictionary
                try:
                    csvdef['postprocess_func'](result_dicts[name])
                except Exception as e:
                    logger.exception(e)
                    print('Postprocessing error:',e)
                    pass

                break
        return FLAG_RESULT
