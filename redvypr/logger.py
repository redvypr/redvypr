import inspect
import logging

class LoggerScan:
    """
    Scans given object recursiely for loggers
    """
    def __init__(self, scanobj):
        self.scanobj = scanobj
        loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        for logger in loggers:
            print('Logger',logger)
            #logger.setLevel(logging.INFO)
        self.logger = []
        self.scanned = []
        self.recursion_level_max = 10
        #self.scan_for_logger(self.scanobj, recursion_level=0)
        #print('Found logger',self.logger)
    def scan_for_logger(self, obj, recursion_level):
        print('Scan for logger',recursion_level)
        if recursion_level > self.recursion_level_max:
            print('Recursion level reached, aborting')
            return

        print('Object',obj,type(obj),'isclass',inspect.isclass(obj),'ismodule', inspect.ismodule(obj))
        if obj in self.scanned:
            print('Scanned already')
            return
        else:
            self.scanned.append(obj)
        # Check if the object is a logger
        if isinstance(obj, logging.Logger):
            print(f"Logger found: {obj.name}")
            self.logger.append(obj)
            return

        # Iterate through attributes of the object
        for name,value in inspect.getmembers(obj):
            print('Member name', name, type(value))
            #if inspect.isclass(obj) or inspect.ismodule(obj):
            if inspect.ismodule(obj):
            #if isinstance(value, object):
                print('Type object',type(value))
                recursion_level_new = recursion_level + 1
                self.scan_for_logger(value,recursion_level=recursion_level_new)
            elif inspect.isclass(obj):
                if hasattr(obj, 'logger'):
                    print('Found logger')
                    self.logger.append(obj.logger)
            elif isinstance(value, dict):
                print('Type dict')
                recursion_level_new = recursion_level + 1
                for v in value.values():
                    if isinstance(v, object):
                        self.scan_for_logger(v,recursion_level=recursion_level_new)
            elif isinstance(value, list):
                recursion_level_new = recursion_level + 1
                for v in value:
                    if isinstance(v, object):
                        self.scan_for_logger(v,recursion_level=recursion_level_new)


