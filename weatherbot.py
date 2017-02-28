#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

    Weather Bot for Telegram.

    Copyright (c) 2017 Oliver Lau <oliver@ersatzworld.net>
    All rights reserved.

"""


import json
import telepot
import shelve
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from telepot.delegate import per_chat_id_in, create_open, pave_event_space, include_callback_query_chat_id
from pprint import pprint
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.job import Job
from pyowm.openweathermap import OpenWeatherMap, degree_to_meteo
from utils import easydict, get_image_from_url


APPNAME = "weatherbot"


def send_weather_report(bot, chat_id):
    global owm
    w = owm.current(2941405)
    msg = "*Current weather in {}*\n\n" \
          "*{:s}* {:.0f} °C ({:.0f} – {:.0f})\n" \
          "wind {:.0f} km/h from {:s}\n" \
          "{}% humidity\n" \
          "sunrise {} / sunset {}\n\n" \
          .format("Burgdorf",
                  w.description,
                  w.temp, w.temp_min, w.temp_max,
                  w.wind_speed,
                  degree_to_meteo(w.wind_degrees),
                  w.humidity,
                  w.sunrise.strftime("%H:%M"),
                  w.sunset.strftime("%H:%M"))
    bot.sendMessage(chat_id, msg, parse_mode="Markdown")


def send_weather_forecast(bot, chat_id):
    global owm
    msg = "*Weather forecast for {}*\n\n".format("Burgdorf")
    try:
        for forecast in owm.forecast_daily(2941405, 7):
            msg += "*{}*\n{:s}, {:.0f} – {:.0f} °C, wind {:.0f} km/h from {:s}\n\n" \
                .format(forecast.date.strftime("%a %d.%m."),
                        forecast.description,
                        forecast.temp_min, forecast.temp_max,
                        forecast.wind_speed,
                        degree_to_meteo(forecast.wind_degrees))
        bot.sendMessage(chat_id, msg, parse_mode="Markdown")
    except telepot.exception.TooManyRequestsError as e:
        bot.sendMessage(chat_id, "Error getting weather data: {}".format(e.description))


def send_weather_forecast_3h(bot, chat_id):
    global owm
    bot.sendMessage(chat_id, "*Weather report for {}*".format("Burgdorf"), parse_mode="Markdown")
    try:
        forecasts = owm.forecast(2941405)
    except telepot.exception.TooManyRequestsError as e:
        bot.sendMessage(chat_id, "Error getting weather data: {}".format(e.description))
    if type(forecasts) is list and len(forecasts) > 0:
        day = forecasts[0].date.day
        msg = forecasts[0].date.strftime("*%a %d.%m.*\n")
        for forecast in forecasts:
            if day == forecast.date.day:
                msg += "*{}* {:s}, {:.0f} – {:.0f} °C, wind {:.0f} km/h from {:s}\n" \
                    .format(forecast.date.strftime("%H:%M"),
                            forecast.description,
                            forecast.temp_min, forecast.temp_max,
                            forecast.wind_speed,
                            degree_to_meteo(forecast.wind_degrees))
            else:
                bot.sendMessage(chat_id, msg, parse_mode="Markdown")
                day = forecast.date.day
                msg = forecast.date.strftime("*%a %d.%m.*\n")
    else:
        bot.sendMessage(chat_id, "Currently no weather data available.")


class ChatUser(telepot.helper.ChatHandler):

    def __init__(self, *args, **kwargs):
        global verbose
        super(ChatUser, self).__init__(*args, **kwargs)
        self.verbose = verbose
        self.owm_job = None

    def open(self, initial_msg, seed):
        content_type, chat_type, chat_id = telepot.glance(initial_msg)
        self.init_scheduler(chat_id)

    def init_scheduler(self, chat_id):
        global settings, scheduler
        hour = settings[chat_id]["report"]["hour"] if type(settings[chat_id]["report"]["hour"]) is int else 6
        self.owm_job = scheduler.add_job(send_weather_forecast,
                                         trigger="cron", hour=hour,
                                         kwargs={"bot": self.bot, "chat_id": chat_id})

    def on__idle(self, event):
        pass

    def on_close(self, msg):
        if self.verbose:
            print("on_close() called. {}".format(msg))
        if type(self.owm_job) is Job:
            self.owm_job.remove()
        return True

    def send_main_menu(self):
        kbd = [InlineKeyboardButton(text="current", callback_data="current"),
               InlineKeyboardButton(text="3h forecast", callback_data="3h"),
               InlineKeyboardButton(text="7 days", callback_data="7d")]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[kbd])
        self.sender.sendMessage("Please choose:", reply_markup=keyboard)

    def on_callback_query(self, msg):
        query_id, from_id, query_data = telepot.glance(msg, flavor="callback_query")
        print("Callback Query:", query_id, from_id, query_data)
        if query_data == "7d":
            self.bot.answerCallbackQuery(query_id, text="Simple weather forecast")
            send_weather_forecast(self.bot, from_id)
        elif query_data == "3h":
            self.bot.answerCallbackQuery(query_id, text="Detailed weather forecast")
            send_weather_forecast_3h(self.bot, from_id)
        elif query_data == "current":
            self.bot.answerCallbackQuery(query_id, text="Current weather report")
            send_weather_report(self.bot, from_id)
        else:
            pass
        self.send_main_menu()

    def on_chat_message(self, msg):
        global scheduler, settings
        content_type, chat_type, chat_id = telepot.glance(msg)
        if content_type == "text":
            if self.verbose:
                pprint(msg)
            msg_text = msg["text"]
            if msg_text.startswith("/start"):
                self.sender.sendMessage("*Hallo, ich bin dein Wetterfrosch-Bot!*",
                                        parse_mode="Markdown")
                self.send_main_menu()
            elif msg_text.startswith("/weather") or msg_text.startswith("wetter"):
                c = msg_text.split()[1:]
                subcmd = c[0].lower() if len(c) > 0 else None
                if subcmd is None or subcmd == "current":
                    send_weather_report(self.bot, chat_id)
                elif subcmd == "simple":
                    send_weather_forecast(self.bot, chat_id)
                elif subcmd in ["detailed", "3h"]:
                    send_weather_forecast_3h(self.bot, chat_id)
            elif msg_text.startswith("/help"):
                self.sender.sendMessage("Available commands:\n\n"
                                        "/help show this message\n"
                                        "/weather Current weather report\n"
                                        "/weather `simple` simple weather forecast\n"
                                        "/weather `detailed` detailed weather forecast\n"
                                        "/start (re)start the bot\n",
                                        parse_mode="Markdown")
            elif msg_text.startswith("/"):
                self.sender.sendMessage("Unknown command. Type /help for further info.")
            else:
                self.sender.sendMessage("I'd don't like to chat. Enter /help for more info.")
        else:
            self.sender.sendMessage("Your '{}' has been moved to Nirvana ...".format(content_type))


# global variables needed for ChatHandler (which unfortunately doesn't allow extra **kwargs)
verbose = False
authorized_users = None
settings = easydict()
scheduler = BackgroundScheduler()
bot = None
owm_api_key = None
owm = None


def main():
    global bot, authorized_users, verbose, settings, scheduler, owm, owm_api_key
    config_filename = "weatherbot-config.json"
    shelf = shelve.open(".weatherbot.shelf")
    if APPNAME in shelf.keys():
        settings = easydict(shelf[APPNAME])
    try:
        with open(config_filename, "r") as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        print("Error: config file '{}' not found: {}"
              .format(config_filename))
        return
    except ValueError as e:
        print("Error: invalid config file '{}': {}"
              .format(config_filename, e))
        return
    telegram_bot_token = config.get("telegram_bot_token")
    if not telegram_bot_token:
        print("Error: config file doesn't contain a `telegram_bot_token`")
        return
    authorized_users = config.get("authorized_users")
    if type(authorized_users) is not list or len(authorized_users) == 0:
        print("Error: config file doesn't contain an `authorized_users` list")
        return
    verbose = config.get("verbose")
    owm_api_key = config.get("openweathermap", {}).get("api_key")
    owm = OpenWeatherMap(owm_api_key) if owm_api_key else None
    bot = telepot.DelegatorBot(telegram_bot_token, [
        include_callback_query_chat_id(pave_event_space())(per_chat_id_in(authorized_users, types="private"),
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
    shelf[APPNAME] = settings
    shelf.sync()
    shelf.close()
    scheduler.shutdown()

if __name__ == "__main__":
    main()
