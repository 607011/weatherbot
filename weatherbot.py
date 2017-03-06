#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

    Weather Bot for Telegram.

    Copyright (c) 2017 Oliver Lau <oliver@ersatzworld.net>
    All rights reserved.

"""

import telepot
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from telepot.delegate import per_chat_id_in, create_open, pave_event_space, include_callback_query_chat_id
from pprint import pprint
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.job import Job
from pyowm.city import CityList
from pyowm.openweathermap import OpenWeatherMap
from utils import *
from enum import Enum

APPNAME = "weatherbot"

# global variables needed for ChatHandler (which unfortunately doesn't allow extra **kwargs)
verbose = False
authorized_users = None
scheduler = BackgroundScheduler()
bot = None
owm_api_key = None
owm = None
city_list = None


def send_weather_report(bot, settings):
    global owm
    w = owm.current(settings["city_id"])
    msg = "*Current weather in {}*\n\n" \
          "*{:s}* {:.0f} °C ({:.0f} – {:.0f} °C)\n" \
          "wind {:.0f} km/h from {:s}\n" \
          "{}% humidity\n" \
          "sunrise {} / sunset {}\n\n" \
          .format(settings.city,
                  w.description,
                  w.temp, w.temp_min, w.temp_max,
                  w.wind_speed,
                  degree_to_meteo(w.wind_degrees),
                  w.humidity,
                  w.sunrise.strftime("%H:%M"),
                  w.sunset.strftime("%H:%M"))
    bot.sendMessage(settings["chat_id"], msg, parse_mode="Markdown")


def send_weather_forecast(bot, settings):
    global owm
    msg = "*Weather forecast for {}*\n\n".format(settings["city"])
    try:
        for forecast in owm.forecast_daily(settings["city_id"], settings["forecast_days"]):
            msg += "*{}*\n{:s}, {:.0f} – {:.0f} °C, wind {:.0f} km/h from {:s}\n\n" \
                .format(forecast.date.strftime("%a %d.%m."),
                        forecast.description,
                        forecast.temp_min, forecast.temp_max,
                        forecast.wind_speed,
                        degree_to_meteo(forecast.wind_degrees))
        bot.sendMessage(settings["chat_id"], msg, parse_mode="Markdown")
    except telepot.exception.TooManyRequestsError as e:
        bot.sendMessage(settings["chat_id"], "Error getting weather data: {}".format(e.description))


def send_weather_forecast_3h(bot, settings):
    global owm
    bot.sendMessage(settings["chat_id"], "*Weather report for {}*".format(settings["city"]), parse_mode="Markdown")
    try:
        forecasts = owm.forecast(settings["city_id"], settings["forecast_periods"])
    except telepot.exception.TooManyRequestsError as e:
        bot.sendMessage(settings["chat_id"], "Error getting weather data: {}".format(e.description))
    if type(forecasts) is list and len(forecasts) > 0:
        day = forecasts[0].date.day
        msg = forecasts[0].date.strftime("*%a %d.%m.*\n")
        for forecast in forecasts:
            if day == forecast.date.day:
                msg += "*{}* {:s}, {} °C, wind {:.0f} km/h from {:s}\n" \
                    .format(forecast.date.strftime("%H:%M"),
                            forecast.description,
                            "{:.0f} – {:.0f}".format(forecast.temp_min, forecast.temp_max)
                                                   if round(forecast.temp_min) != round(forecast.temp_max)
                                                   else "{:.0f}".format(forecast.temp_min),
                            forecast.wind_speed,
                            degree_to_meteo(forecast.wind_degrees))
            else:
                bot.sendMessage(settings["chat_id"], msg, parse_mode="Markdown")
                day = forecast.date.day
                msg = forecast.date.strftime("*%a %d.%m.*\n")
    else:
        bot.sendMessage(settings["chat_id"], "Currently no weather data available.")


class Settings(PersistentDict):
    DefaultCity = "Burgdorf"
    DefaultCityId = 2941405
    DefaultForecastDays = 7
    DefaultForecastPeriods = 24//3*5
    DefaultHour = 6

    def __init__(self, chat_id):
        super(Settings, self).__init__(".weatherbot-settings-{}.json".format(chat_id))
        self["chat_id"] = chat_id
        self["report_hour"] = self.get("report_hour", Settings.DefaultHour)
        self["city_id"] = self.get("city_id", Settings.DefaultCityId)
        self["city"] = self.get("city", Settings.DefaultCity)
        self["forecast_days"] = self.get("forecast_days", Settings.DefaultForecastDays)
        self["forecast_periods"] = self.get("forecast_periods", Settings.DefaultForecastPeriods)


class ChatUser(telepot.helper.ChatHandler):

    class State(Enum):
        Default = 1
        AwaitingCityName = 2
        AwaitingCitySelection = 3

    def __init__(self, *args, **kwargs):
        global verbose
        super(ChatUser, self).__init__(*args, **kwargs)
        self.verbose = verbose
        self.owm_job = None
        self.state = ChatUser.State.Default
        self.settings = Settings(self.chat_id)
        self.city_choices = []

    def open(self, initial_msg, seed):
        content_type, chat_type, chat_id = telepot.glance(initial_msg)
        self.settings = Settings(chat_id)
        print(self.settings)
        self.init_scheduler(chat_id)

    def init_scheduler(self, chat_id):
        global scheduler
        self.owm_job = scheduler.add_job(
            send_weather_forecast,
            trigger="cron", hour=self.settings["report_hour"],
            kwargs={"bot": self.bot,
                    "settings": self.settings})

    def on__idle(self, event):
        if self.verbose:
            print("idling ...")

    def on_close(self, msg):
        pprint(msg)
        content_type, chat_type, chat_id = telepot.glance(msg)
        if chat_id == self.chat_id:
            self.settings.sync()
        else:
            print("Warning: received chat_id doesn't equal self.chat_id.")
        if self.verbose:
            print("on_close() called. {}".format(msg))
        if type(self.owm_job) is Job:
            self.owm_job.remove()
        return True

    def send_main_menu(self):
        kbd = [InlineKeyboardButton(text="current", callback_data="current"),
               InlineKeyboardButton(text="simple", callback_data="7d"),
               InlineKeyboardButton(text="detailed", callback_data="3h")]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[kbd])
        self.sender.sendMessage("Please choose:", reply_markup=keyboard)

    def on_callback_query(self, msg):
        query_id, from_id, query_data = telepot.glance(msg, flavor="callback_query")
        if self.verbose:
            print("Callback Query:", query_id, from_id, query_data)
        if query_data == "7d":
            self.bot.answerCallbackQuery(
                query_id,
                text="Simple weather forecast for {}".format(self.settings["city"]))
            send_weather_forecast(self.bot, self.settings)
        elif query_data == "3h":
            self.bot.answerCallbackQuery(
                query_id,
                text="Detailed weather forecast for {}".format(self.settings["city"]))
            send_weather_forecast_3h(self.bot, self.settings)
        elif query_data == "current":
            self.bot.answerCallbackQuery(
                query_id,
                text="Current weather report for {}".format(self.settings["city"]))
            send_weather_report(self.bot, self.settings)
        else:
            pass
        self.send_main_menu()

    def on_chat_message(self, msg):
        global scheduler, city_list
        content_type, chat_type, chat_id = telepot.glance(msg)
        print(chat_id, self.chat_id)
        if content_type == "text":
            if self.verbose:
                pprint(msg)
            msg_text = msg["text"]
            if msg_text.startswith("/help"):
                self.send_help()
            elif msg_text.startswith("/selectcity"):
                self.sender.sendMessage("The currently selected city is \"{}\". "
                                        "Tell me the name of the city you'd like reports/forecasts for."
                                        .format(self.settings["city"]))
                self.state = ChatUser.State.AwaitingCityName
            elif self.state == ChatUser.State.Default:
                if msg_text.startswith("/start"):
                    self.sender.sendMessage("*Hi there, I'm your personal meteorological bot!* " +
                                            chr(0x2600) + chr(0x26C5),
                                            parse_mode="Markdown")
                    self.send_help()
                elif msg_text.startswith("/weather") or msg_text.startswith("wetter"):
                    c = msg_text.split()[1:]
                    subcmd = c[0].lower() if len(c) > 0 else None
                    if subcmd is None:
                        self.send_main_menu()
                    elif subcmd == "current":
                        send_weather_report(self.bot, self.settings)
                    elif subcmd == "simple":
                        send_weather_forecast(self.bot, self.settings)
                    elif subcmd in ["detailed", "3h"]:
                        send_weather_forecast_3h(self.bot, self.settings)
                elif msg_text.startswith("/"):
                    self.sender.sendMessage("Unknown command. Type /help for further info.")

            elif self.state == ChatUser.State.AwaitingCityName:
                self.city_choices = list(city_list.find(msg_text))
                if len(self.city_choices) > 1:
                    msg = "Found {} cities that match \"{}\". "\
                        "Please select one by typing its number:"\
                        .format(len(self.city_choices), msg_text)
                    self.send_city_choices(msg)
                elif len(self.city_choices) == 1:
                    self.settings["city"] = self.city_choices[0]["name"]
                    self.settings["city_id"] = self.city_choices[0]["_id"]
                    self.sender.sendMessage("From now on you'll receive reports/forecasts for {}."
                                            .format(self.settings["city"]))
                    self.settings.sync()
                    self.state = ChatUser.State.Default
                else:
                    self.sender.sendMessage("There's no weather data available for \"{}\". Please try again."
                                            .format(msg_text))

            elif self.state == ChatUser.State.AwaitingCitySelection:
                if len(msg_text) > 0 and msg_text[0] == "/":
                    msg_text = msg_text[1:]
                try:
                    idx = int(msg_text) - 1
                except ValueError:
                    self.sender.sendMessage("Please type a number between 1 and {}.".format(len(self.city_choices)))
                else:
                    if 0 <= idx < len(self.city_choices):
                        self.settings["city"] = self.city_choices[idx]["name"]
                        self.settings["city_id"] = self.city_choices[idx]["_id"]
                        self.sender.sendMessage("All further reports/forecasts will refer to \"{}\" (#{:d})."
                                                .format(self.settings["city"], self.settings["city_id"]))
                        self.settings.sync()
                        self.state = ChatUser.State.Default
                    else:
                        self.send_city_choices("Invalid selection. Please try again.")
            elif msg_text.startswith("/"):
                self.sender.sendMessage("Unknown command. Type /help for further info.")
            else:
                self.sender.sendMessage("Enter /help for more info.")
        else:
            self.sender.sendMessage("Your \"{}\" has been moved to Nirvana ...".format(content_type))

    def send_city_choices(self, msg):
        msg += "\n\n"
        code = 1
        for city in self.city_choices:
            msg += "/{:d} – {} (<a href=\"https://maps.google.com/maps?q={:.7f},{:.7f}\">{:.3f} {:.3f}</a> #{:d})\n" \
                .format(code, city["name"],
                        city["coord"]["lat"], city["coord"]["lon"],
                        city["coord"]["lat"], city["coord"]["lon"],
                        city["_id"])
            code += 1
        msg += "\n<i>Hint: "\
               "You can tap/click on the coordinates to open Google Maps "\
               "at the respective latitude/longitude "\
               "if you're unsure which option is correct.</i>"
        self.sender.sendMessage(msg, parse_mode="HTML")
        self.state = ChatUser.State.AwaitingCitySelection

    def send_help(self):
        self.sender.sendMessage("Available commands:\n\n"
                                "/help show this message\n"
                                "/weather Show weather report/forecast options\n"
                                "/weather `current` current weather\n"
                                "/weather `simple` simple weather forecast\n"
                                "/weather `detailed` detailed weather forecast\n"
                                "/selectcity select the city you want reports and forecasts for\n"
                                "/start (re)start the bot\n",
                                parse_mode="Markdown")


def main():
    global bot, authorized_users, verbose, scheduler, owm, owm_api_key, city_list
    config_filename = "weatherbot-config.json"
    try:
        with open(config_filename, "r") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        print("Error: config file '{}' not found: {}".format(config_filename))
        return
    except ValueError as e:
        print("Error: invalid config file '{}': {}".format(config_filename, e))
        return
    telegram_bot_token = config.get("telegram_bot_token")
    if not telegram_bot_token:
        print("Error: config file doesn't contain a `telegram_bot_token`")
        return
    authorized_users = config.get("authorized_users")
    if type(authorized_users) is not list or len(authorized_users) == 0:
        print("Error: config file doesn't contain an `authorized_users` list")
        return
    verbose = config.get("verbose", True)
    owm_api_key = config.get("openweathermap", {}).get("api_key")
    owm = OpenWeatherMap(owm_api_key) if owm_api_key else None

    city_list_filename = config.get("openweathermap", {}).get("city_list")
    city_list = CityList()
    if city_list_filename:
        print("Loading city list ...")
        city_list.read(city_list_filename)

    bot = telepot.DelegatorBot(telegram_bot_token, [
        include_callback_query_chat_id(
            pave_event_space())(per_chat_id_in(authorized_users, types="private"),
                                create_open,
                                ChatUser,
                                timeout=3600)
    ])
    scheduler.start()
    try:
        bot.message_loop(run_forever="Bot listening ...")
    except KeyboardInterrupt:
        pass
    if verbose:
        print("Exiting ...")
    scheduler.shutdown()

if __name__ == "__main__":
    main()
