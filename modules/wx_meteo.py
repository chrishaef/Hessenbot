#import openmeteo_requests # pip install openmeteo-requests
#from retry_requests import retry # pip install retry_requests

import requests
import json
from modules.log import logger
from modules.settings import ERROR_FETCHING_DATA
from modules.locale_de import wmo_weather_de, wind_direction_de

def get_weather_data(api_url, params):
    response = requests.get(api_url, params=params)
    response.raise_for_status()  # Raise an error for bad status codes
    return response.json()

def get_wx_meteo(lat=0, lon=0, unit=0):
	# set forcast days 1 or 3
	forecastDays = 3

	# Make sure all required weather variables are listed here
	# The order of variables in hourly or daily is important to assign them correctly below
	url = "https://api.open-meteo.com/v1/forecast"
	params = {
		"latitude": {lat},
		"longitude": {lon},
		"daily": ["weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_hours", "precipitation_probability_max", "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant"],
		"timezone": "auto",
		"forecast_days": {forecastDays}
	}

	# Unit 0 is imperial, 1 is metric
	if unit == 0:
		params["temperature_unit"] = "fahrenheit"
		params["wind_speed_unit"] = "mph"
		params["precipitation_unit"] = "inch"
		params["distance_unit"] = "mile"
		params["pressure_unit"] = "inHg"

	try:
		# Fetch the weather data
		weather_data = get_weather_data(url, params)
	except Exception as e:
		logger.error(f"Error fetching meteo weather data: {e}")
		return ERROR_FETCHING_DATA

	# Check if we got a response
	try:
		# Process location
		logger.debug(f"System: Pulled from Open-Meteo in {weather_data['timezone']} {weather_data['timezone_abbreviation']}")
		
		# Ensure response is defined
		response = weather_data
		
		# Process daily data. The order of variables needs to be the same as requested.
		daily = response['daily']
		daily_weather_code = daily['weather_code']
		daily_temperature_2m_max = daily['temperature_2m_max']
		daily_temperature_2m_min = daily['temperature_2m_min']
		daily_precipitation_hours = daily['precipitation_hours']
		daily_precipitation_probability_max = daily['precipitation_probability_max']
		daily_wind_speed_10m_max = daily['wind_speed_10m_max']
		daily_wind_gusts_10m_max = daily['wind_gusts_10m_max']
		daily_wind_direction_10m_dominant = daily['wind_direction_10m_dominant']
	except Exception as e:
		logger.error(f"Error processing meteo weather data: {e}")
		return ERROR_FETCHING_DATA

	# create a weather report (Deutsch)
	weather_report = ""
	for i in range(forecastDays):
		wind_direction = wind_direction_de(daily_wind_direction_10m_dominant[i])

		if str(i + 1) == "1":
			weather_report += "Heute: "
		elif str(i + 1) == "2":
			weather_report += "Morgen: "
		else:
			weather_report += f"Tag {i + 1}: "

		code_string = wmo_weather_de(daily_weather_code[i])
		weather_report += code_string + ". "

		if unit == 0:
			weather_report += (
				f"Max {int(round(daily_temperature_2m_max[i]))}°F, "
				f"min {int(round(daily_temperature_2m_min[i]))}°F. "
			)
		else:
			weather_report += (
				f"Max {int(round(daily_temperature_2m_max[i]))}°C, "
				f"min {int(round(daily_temperature_2m_min[i]))}°C. "
			)

		if daily_precipitation_hours[i] > 0:
			if unit == 0:
				weather_report += (
					f"Niederschlag {round(daily_precipitation_probability_max[i], 0)}% "
					f"in {round(daily_precipitation_hours[i], 1)} h. "
				)
			else:
				weather_report += (
					f"Niederschlag {round(daily_precipitation_probability_max[i], 0)}% "
					f"in {round(daily_precipitation_hours[i], 1)} h. "
				)
		else:
			weather_report += "Kein Niederschlag. "

		if daily_wind_speed_10m_max[i] > 0:
			if unit == 0:
				weather_report += (
					f"Wind {int(round(daily_wind_speed_10m_max[i]))} mph, "
					f"Böen bis {int(round(daily_wind_gusts_10m_max[i]))} mph aus {wind_direction}."
				)
			else:
				weather_report += (
					f"Wind {int(round(daily_wind_speed_10m_max[i]))} km/h, "
					f"Böen bis {int(round(daily_wind_gusts_10m_max[i]))} km/h aus {wind_direction}."
				)
		else:
			weather_report += "Windstill."

		# add a new line for the next day
		if i < forecastDays - 1:
			weather_report += "\n"

	return weather_report

def get_flood_openmeteo(lat=0, lon=0):
	# set forcast days 1 or 3
	forecastDays = 3

	# Flood data
	url = "https://flood-api.open-meteo.com/v1/flood"
	params = {
		"latitude": {lat},
		"longitude": {lon},
		"timezone": "auto",
		"daily": "river_discharge",
		"forecast_days": forecastDays
	}

	try:
		# Fetch the flood data
		flood_data = get_weather_data(url, params)
	except Exception as e:
		logger.error(f"Error fetching meteo flood data: {e}")
		return ERROR_FETCHING_DATA
	
	# Check if we got a response
	try:
		# Process location
		logger.debug(f"System: Pulled River FLow Data from Open-Meteo {flood_data['timezone_abbreviation']}")
		
		# Ensure response is defined
		response = flood_data
		
		# Process daily data. The order of variables needs to be the same as requested.
		daily = response['daily']
		daily_river_discharge = daily['river_discharge']
		# check if none

	except Exception as e:
		logger.error(f"Error processing meteo flood data: {e}")
		return ERROR_FETCHING_DATA
	
	# create a flood report
	flood_report = ""
	flood_report += "River Discharge: " + str(daily_river_discharge) + "m3/s"

	return flood_report
