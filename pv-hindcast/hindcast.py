#! /usr/bin/python

import pvlib
import pandas as pd
import datetime

import matplotlib.pyplot as plt

import seaborn as sns
sns.set_color_codes()

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


# Parse the weather data to a frame of series.
# Unfortunately, seems pd can't handle appending, so we build lists.
data = {
        'time' : [],
        'ghi' : [],
        'dni' : [],
        'dhi' : [],
        'dni_extra' : [],
        'wind_speed': [],
        'temp_air': [],
        'pressure': [],
        'albedo': []
}
with open('../data/NUNAVUT/IqaluitA_1953-2005/16603.WY2') as f:
    for line in f:
        ##### just simulate 1953!
        if line[6:10] != '1953': break

        # yyyymmdd
        str_ymd = line[6:14]
        # hh but from 01 to 24 not from 00 to 23, so we need to interpret it
        str_hr = line[14:16]

        # values in kJ/m^2 for the entire hour; divide by 3.6 to get W/m^2
        str_extra = line[16:20] # extraterrestrial irradiance (sun at ToA)
        str_ghi = line[20:24] # global horizontal irradiance
        str_dni = line[26:30] # direct normal irradiance
        str_dhi = line[32:36] # diffuse horizontal irradiance (ghi - dni)
        # pressure in 10 Pa ; divide by 100 to get kPa
        str_pressure = line[85:90]
        # value in 0.1 C ; divide by 10 to get C
        str_temp = line[91:95]
        # value in 0.1 m/s ; divide by 10 to get m/s.
        str_wind = line[105:109]
        # 0 => no snow; 1 => snow; 99 => missing
        str_snow = line[116:118]

        # parse the date
        time = pd.to_datetime(str_ymd, format='%Y%m%d').tz_localize('Canada/Eastern')
        if str_hr == '24':
            time += datetime.timedelta(days = 1)
        else:
            time += datetime.timedelta(hours = int(str_hr))
        data['time'].append(time)

        # parse irradiance
        data['dni_extra'].append(int(str_extra) / 3.6)
        data['ghi'].append(int(str_ghi) / 3.6)
        data['dni'].append(int(str_dni) / 3.6)
        data['dhi'].append(int(str_dhi) / 3.6)

        # parse the weather
        data['wind_speed'].append(int(str_wind) / 10.0)
        data['temp_air'].append(int(str_temp) / 10.0)
        data['pressure'].append(int(str_pressure) / 100.0)

        if str_snow == '0':
            data['albedo'].append(pvlib.irradiance.SURFACE_ALBEDOS['soil'])
        elif str_snow == '1':
            data['albedo'].append(pvlib.irradiance.SURFACE_ALBEDOS['snow'])
        else:
            # Missing. Shitty guess: assume it's snowy if temp < -3 (bad guess!)
            # we probably should guess based on a model that includes precip data and
            # recent temps, which we have access to
            if data['temp_air'][-1] < -3:
                data['albedo'].append(pvlib.irradiance.SURFACE_ALBEDOS['snow'])
            else:
                data['albedo'].append(pvlib.irradiance.SURFACE_ALBEDOS['soil'])


# build up a dataframe.
# Why not do it while parsing? Because pd is stupid -- you can't add rows efficiently.
# To get better performance we'd need to manually do the array growing as we read in data.
data = pd.DataFrame(data, index = data['time'])
del data['time']
#print ("Got the data: ", data)

# Get the sun positions.
solpos = pvlib.solarposition.get_solarposition(data.index, latlong[0], latlong[1])
#print ("Got the solpos: ", solpos)

# Get the irradiance on the panel.
irradiance = pvlib.irradiance.total_irrad(
                surface_tilt, surface_azimuth,
                solpos['apparent_zenith'], solpos['azimuth'],
                data['dni'], data['ghi'], data['dhi'],
                dni_extra = data['dni_extra'],
                albedo = data['albedo'],
                model='haydavies')
irradiance.fillna(0, inplace=True)
#print ("Got the irradiance: ", irradiance)

# Model the PV panel temperature.
panel_temp = pvlib.pvsystem.sapm_celltemp(irradiance['poa_global'],
        data['wind_speed'], data['temp_air'])
#print ("Got the panel temps: ", panel_temp)

# Get the effective irradiance, which differs from irradiance... somehow.
# For that we need the angle of incidence, which I guess didn't already get figured,
# and something about the atmosphere which matters why?
# Who the fuck wrote this shit?
aoi = pvlib.irradiance.aoi(surface_tilt, surface_azimuth,
                solpos['apparent_zenith'], solpos['azimuth'])
airmass = pvlib.atmosphere.relativeairmass(solpos['apparent_zenith'])
am_abs = pvlib.atmosphere.absoluteairmass(airmass, data['pressure'])
#print ("Got the air mass: ", am_abs)
effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(
                irradiance['poa_direct'], irradiance['poa_diffuse'],
                am_abs, aoi, module)
#print ("Got the effective irradiance: ", effective_irradiance)

# Finally, we can get the DC out from the panel, and the AC out from the inverter.
# Units for AC is watts; DC has several outputs, we use voltage and watts.
dc = pvlib.pvsystem.sapm(effective_irradiance, panel_temp['temp_cell'], module)
ac = pvlib.pvsystem.snlinverter(dc['v_mp'], dc['p_mp'], inverter)

# Plotting:
# - group by year
#      print the daily totals (see variation by time of year)
#      - group by month
#           print the daily totals (see variation by day)
#           print total of each hour (see variation by time of day)
# print the years (see variation by year)

def doplot(series, numhours, filename, title, extraseries = None):
    maxgeneration = numhours * inverter.Paco
    generation = series.sum()
    capacity_factor = generation / maxgeneration * 100.0

    ax = series.plot(legend = None)
    if extraseries is not None:
        extraseries.plot(grid=False, legend=None, color='green')

    ax.set_ylim(ymin = 0)
    plt.title(title + '; sum {} kWh ({}% capacity)'.format(int(generation) / 1000.0, int(capacity_factor)))
    plt.savefig(filename + '.pdf')
    plt.gcf().clear()

# Group by year
years = ac.groupby(pd.TimeGrouper('A'))
for year, yeardata in years:
    print ("Year {} group : {}".format(year, yeardata))
    numhours = len(yeardata)
    daily_in_year = yeardata.resample('D').sum()
    average_day_per_month = daily_in_year.resample('M').mean().tshift(-15, 'D')
    print ("Year {} month averages : {}".format(year, average_day_per_month))

    doplot(daily_in_year, numhours, "year-{:02d}".format(year.year),
        "Year {:02d}".format(year.year), extraseries = average_day_per_month)

    months = yeardata.groupby(pd.TimeGrouper('M'))
    for month, monthdata in months:
        print ("Month {}".format(month))
        # print daily data
        numhours = len(monthdata)
        monthname = '{:04d}-{:02d}'.format(month.year, month.month)
        doplot(monthdata.resample('D').sum(), numhours, "month-{}".format(monthname),
            "Month {}".format(monthname))
        # print hourly data averaged by the day of the month
        doplot(monthdata.groupby(monthdata.index.hour).mean(), 24, "average-day-{}".format(monthname),
            "Average daily {}".format(monthname))
