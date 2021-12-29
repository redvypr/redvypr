import time


def redvypr_datadict(data,datakey=None,tu=None):
    """ A datadictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()
    if(datakey == None):
        datakey = 'data'
        
    datadict = {'t':tu}
    datadict[datakey] = data
    return datadict
