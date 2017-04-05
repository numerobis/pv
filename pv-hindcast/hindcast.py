#! /usr/bin/python

import pvlib
import pandas as pd
import datetime
import numpy as np
import zipfile

import matplotlib.pyplot as plt

import seaborn as sns
sns.set_color_codes()

# TODO: generalize this by reading metadata somehow.
latitude = 63.75
longitude = -68.55

def read_weather_data(purge_cache = False):
    """
    Look up the weather data for Iqaluit for the given years.

    We calculate everything that doesn't depend on the module & inverter.

    Returns a dataframe with indices the times (hourly data),
    columns for weather, albedo, irradiance (ghi/dni/dhi),
    solar position, etc.

    We cache the data if possible.
    If 'purge_cache' is set, we ignore any existing cache and clobber it.
    """
    data = None
    if not purge_cache:
      try:
        data = pd.read_pickle('data-cache.bin')
      except:
        # cache is missing or bad; ignore it.
        pass
    if data is None:
        data = _read_weather_data()
        data.to_pickle('data-cache.bin')
    return data

def _read_weather_data():
    """
    Read the text file. This is rather slow.
    """
    # Parse the weather data to a frame of series.
    # Unfortunately, seems pd can't handle appending, so we build lists.
    times = []
    ghi = []
    dni = []
    dhi = []
    dni_extra = []
    wind_speed = []
    temp_air = []
    pressure = []
    albedo = []

    # we use these a lot, save some lookups
    albedo_soil = pvlib.irradiance.SURFACE_ALBEDOS['soil']
    albedo_snow = pvlib.irradiance.SURFACE_ALBEDOS['snow']

    with zipfile.ZipFile('../data/NUNAVUT.zip') as zipf:
      with zipf.open('NUNAVUT/IqaluitA_1953-2005/16603.WY2') as f:
        for line in f:
            # yyyymmdd
            str_ymd = line[6:14]
            # hh but from 01 to 24 not from 00 to 23, so we need to interpret it (subtract one)
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
            time += datetime.timedelta(hours = int(str_hr) - 1)
            times.append(time)

            # parse irradiance
            dni_extra.append(int(str_extra) / 3.6)
            ghi.append(int(str_ghi) / 3.6)
            dni.append(int(str_dni) / 3.6)
            dhi.append(int(str_dhi) / 3.6)

            # parse the weather
            wind_speed.append(int(str_wind) / 10.0)
            temp_air.append(int(str_temp) / 10.0)
            pressure.append(int(str_pressure) / 100.0)

            if str_snow == '0':
                albedo.append(albedo_soil)
            elif str_snow == '1':
                albedo.append(albedo_snow)
            else:
                # Missing. Shitty guess: assume it's snowy if temp < -3 (bad guess!)
                # we probably should guess based on a model that includes precip data and
                # recent temps, which we have access to
                if temp_air[-1] < -3:
                    albedo.append(albedo_snow)
                else:
                    albedo.append(albedo_soil)

    # Pack the data now, before using it below.
    times = np.asarray(times)
    ghi = np.asarray(ghi, dtype=np.float32)
    dni = np.asarray(dni, dtype=np.float32)
    dhi = np.asarray(dhi, dtype=np.float32)
    dni_extra = np.asarray(dni_extra, dtype=np.float32)
    wind_speed = np.asarray(wind_speed, dtype=np.float32)
    temp_air = np.asarray(temp_air, dtype=np.float32)
    pressure = np.asarray(pressure, dtype=np.float32)
    albedo = np.asarray(albedo, dtype=np.float32)

    # We don't get zenith/azimuth from the data. Calculate it.
    solpos = pvlib.solarposition.get_solarposition(times, latitude, longitude)
    solar_zenith = np.asarray(solpos['apparent_zenith'], dtype=np.float32)
    solar_azimuth = np.asarray(solpos['azimuth'], dtype=np.float32)

    # Get the air mass (?)
    airmass = pvlib.atmosphere.relativeairmass(solar_zenith)
    am_abs = pvlib.atmosphere.absoluteairmass(airmass, pressure)
    am_abs = np.asarray(am_abs, dtype=np.float32)

    return pd.DataFrame({
        'ghi' : ghi,
        'dni' : dni,
        'dhi' : dhi,
        'dni_extra': dni_extra,
        'wind_speed': wind_speed,
        'temp_air' : temp_air,
        'pressure' : pressure,
        'albedo' : albedo,
        'solar_zenith' : solar_zenith,
        'solar_azimuth' : solar_azimuth,
        'absolute_airmass': am_abs
    }, index = times)

def get_watts_out(data, module, inverter, surface_tilt, surface_azimuth = 180):
    # Get the irradiance on the panel.
    irradiance = pvlib.irradiance.total_irrad(
                    surface_tilt, surface_azimuth,
                    data['solar_zenith'], data['solar_azimuth'],
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
    aoi = pvlib.irradiance.aoi(surface_tilt, surface_azimuth,
                    data['solar_zenith'], data['solar_azimuth'])
    effective_irradiance = pvlib.pvsystem.sapm_effective_irradiance(
                    irradiance['poa_direct'], irradiance['poa_diffuse'],
                    data['absolute_airmass'], aoi, module)
    #print ("Got the effective irradiance: ", effective_irradiance)

    # Finally, we can get the DC out from the panel, and the AC out from the inverter.
    # Units for AC is watts; DC has several outputs, we use voltage and watts.
    dc = pvlib.pvsystem.sapm(effective_irradiance, panel_temp['temp_cell'], module)
    ac = pvlib.pvsystem.snlinverter(dc['v_mp'], dc['p_mp'], inverter)
    return ac

def plot(series, filename,
        title = None,
        xlabel = None,
        ylabel = None,
        mainlegend = None,
        extralegend = None,
        xtics_count = None,
        yrange = (None, None),
        extraseries = None):
    ax = series.plot(legend = mainlegend, grid=True)
    if extraseries is not None:
        extraseries.plot(grid=False, legend=None, color='green')

    plt.title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel(xlabel)

    if yrange[0] is not None:
        ax.set_ylim(ymin = yrange[0])

    if yrange[1] is not None:
        ax.set_ylim(ymax = yrange[1])

    if xtics_count is not None:
        start, stop = ax.get_xlim()
        ax.set_xticks(np.arange(start, stop, (stop - start) / xtics_count))

    plt.savefig(filename + '.pdf')
    plt.gcf().clear()

def plot_watts_out(series, inverter, filename, title,
        hours_per_item = 1, extraseries = None, xlabel = None, ylabel = None,
        ymax = None):
    maxgeneration = hours_per_item * len(series) * inverter.Paco
    generation = series.sum()
    capacity_factor = generation / maxgeneration * 100.0

    title += ': {:.2f} kWh ({}% capacity)'.format(int(generation) / 1000.0, int(capacity_factor))

    plot(series, filename,
        title = title,
        xlabel = xlabel, ylabel = ylabel,
#        mainlegend = mainlegend,
#        extralegend = extralegend,
#        xtics_count = xtics_count,
        yrange = (0, ymax),
        extraseries = extraseries)

if __name__ == '__main__':
    # Select the PV module and the inverter.
    sandia_modules = pvlib.pvsystem.retrieve_sam('SandiaMod')
    sapm_inverters = pvlib.pvsystem.retrieve_sam('cecinverter')
    module = sandia_modules['Canadian_Solar_CS5P_220M___2009_']
    inverter = sapm_inverters['ABB__MICRO_0_25_I_OUTD_US_208_208V__CEC_2014_']

    # Select the location. Iqaluit A.
    latlong = (63.75, -68.55)
    data = read_weather_data(latitude = latlong[0], longitude = latlong[1])
    #print ("Got the data: ", data)

    # Select the inclination of the panel. Normally ~ the latitude, and south (180).
    # Latitude means max power at noon on equinox.
    surface_tilt = abs(latlong[0])
    surface_azimuth = 180

    ac = get_watts_out(data, module, inverter, surface_tilt, surface_azimuth)

    # Plotting:
    # - group by year
    #      print the daily totals (see variation by time of year)
    #      - group by month
    #           print the daily totals (see variation by day)
    #           print total of each hour (see variation by time of day)
    # print the years (see variation by year)


    # Group by year
    years = ac.groupby(pd.TimeGrouper('A'))
    for year, yeardata in years:
        print ("Year {} group : {}".format(year, yeardata))
        numhours = len(yeardata)
        daily_in_year = yeardata.resample('D').sum()
        average_day_per_month = daily_in_year.resample('M').mean().tshift(-15, 'D')
        print ("Year {} month averages : {}".format(year, average_day_per_month))

        plot_watts_out(daily_in_year, inverter, numhours, "year-{:02d}".format(year.year),
            "Year {:02d}".format(year.year), extraseries = average_day_per_month)

        months = yeardata.groupby(pd.TimeGrouper('M'))
        for month, monthdata in months:
            print ("Month {}".format(month))
            # print daily data
            numhours = len(monthdata)
            monthname = '{:04d}-{:02d}'.format(month.year, month.month)
            plot_watts_out(monthdata.resample('D').sum(), inverter, numhours, "month-{}".format(monthname),
                "Month {}".format(monthname))
            # print hourly data averaged by the day of the month
            plot_watts_out(monthdata.groupby(monthdata.index.hour).mean(), inverter, 24, "average-day-{}".format(monthname),
                "Average daily {}".format(monthname))
