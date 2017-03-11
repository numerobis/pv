#! /usr/bin/python

import pvlib
import pandas
import datetime

# Select the PV module and the inverter.
sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
sapm_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
module = sandia_modules['Canadian_Solar_CS5P_220M___2009_']
inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208_208V__CEC_2014_']

# Select the location. Iqaluit A.
latlong = (63.75, -68.55)

# Select the inclination of the panel. Normally ~ the latitude, and south (180).
# Latitude means max power at noon on equinox.
surface_tilt = latlong[0]
surface_azimuth = 180

start_date = None
end_date = None

# Look up the weather data
with open('../data/NUNAVUT/IqaluitA_1953-2005/16603.WY2') as f:
    for line in f:
        ##### just simulate 1953!
        if line[6:10] != '1953': break

        # yyyymmdd
        str_ymd = line[6:14]
        # hh but from 01 to 24 not from 00 to 23, so we need to interpret it
        str_hr = line[14:16]

        # values in kJ/m^2 for the entire hour; divide by 3.6 to get W/m^2
        str_ghi = line[20:24] # global horizontal irradiance
        str_dni = line[26:30] # direct normal irradiance
        str_dhi = line[32:36] # diffuse horizontal irradiance (ghi - dni)
        # value in 0.1 C ; divide by 10 to get C
        str_temp = line[91:95]
        # value in 0.1 m/s ; divide by 10 to get m/s.
        str_wind = line[105:109]

        # parse the date
        the_time = pandas.to_datetime(str_ymd, format='%Y%m%d').tz_localize('Canada/Eastern')
        if str_hr == '24':
            the_time += datetime.timedelta(days = 1)
        else:
            the_time += datetime.timedelta(hours = int(str_hr))
        the_time_printable = the_time.isoformat(' ')

        # parse irradiance
        irradiance = {
                'ghi': int(str_ghi) / 3.6,
                'dni': int(str_dni) / 3.6,
                'dhi': int(str_dhi) / 3.6,
        }

        # parse the weather
        weather = {
                 'wind_speed' : int(str_wind) / 10.0,
                 'temp_air' : int(str_temp) / 10.0,
        }

        # if there's no irradiance, don't call -- it causes an exception
        if irradiance['ghi'] == 0: 
            print ("{0} 0".format(the_time_printable))
        else:
            (dc, ac) = pvlib.modelchain.basic_chain([the_time],
                    latlong[0], latlong[1],
                    module, inverter,
                    surface_tilt=surface_tilt, surface_azimuth=surface_azimuth, 
                    irradiance=irradiance, weather=weather)
            print("{0} {1} {2} {3} {4} {5} {6}".format(the_time_printable, ac[0],
                irradiance['ghi'], irradiance['dni'], irradiance['dhi'],
                weather['wind_speed'], weather['temp_air']))
