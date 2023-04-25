import datetime


def NMEA_position(csvdict):
    """
    Returns the position using the NMEA fields
    """
    if(csvdict['EW'].lower() =='w'):
        lonfac = 1.0
    else:
        lonfac = -1.0
    lon = lonfac * csvdict['longitude']
    csvdict['londeg'] = lon

    if(csvdict['NS'].lower() =='n'):
        latfac = 1.0
    else:
        latfac = -1.0
    lat = latfac * csvdict['latitude']
    csvdict['latdeg'] = lat


def NMEA_position_date(csvdict):
    """
    Add the position in decimal degrees to the dictionary as well as a datetime object
    """
    #'172740.750'
    tstr = csvdict['date']+csvdict['time']
    #print(csvdict)
    #print('tstr',tstr)
    td = datetime.datetime.strptime(tstr, '%d%m%y%H%M%S.%f')
    csvdict['datetime'] = td

    if(csvdict['EW'].lower() =='w'):
        lonfac = 1.0
    else:
        lonfac = -1.0
    lon = lonfac * csvdict['longitude']
    csvdict['londeg'] = lon

    if(csvdict['NS'].lower() =='n'):
        latfac = 1.0
    else:
        latfac = -1.0
    lat = latfac * csvdict['latitude']
    csvdict['latdeg'] = lat


