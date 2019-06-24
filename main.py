import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram.error import TelegramError
import logging

import uuid
import sys
import os
import time
from enum import Enum

with open("data/token.txt", "r") as f:
    API_KEY = f.read().rstrip()

def get_static_handler(command):
    """
    Given a string command, returns a CommandHandler for that string that
    responds to messages with the content of static_responses/[command].txt

    Throws IOError if file does not exist or something
    """

    f = open("static_responses/{}.txt".format(command), "r")
    response = f.read()

    return CommandHandler(command, \
        ( lambda bot, update : \
        bot.send_message(chat_id=update.message.chat.id, text=response) ) )

# Credit: https://github.com/CaKEandLies/Telegram_Cthulhu/blob/master/cthulhu_game_bot.py#L63
def feedback_handler(bot, update, args=None):
    """
    Store feedback from users in a text file.
    """
    if args and len(args) > 0:
        feedback = open("ignore/feedback.txt", "a")
        feedback.write("\n")
        feedback.write(update.message.from_user.first_name)
        feedback.write("\n")
        # Records User ID so that if feature is implemented, can message them
        # about it.
        feedback.write(str(update.message.from_user.id))
        feedback.write("\n")
        feedback.write(" ".join(args))
        feedback.write("\n")
        feedback.close()
        bot.send_message(chat_id=update.message.chat_id,
                         text="Thanks for the feedback!")
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Format: /feedback [feedback]")

def handle_error(bot, update, error):
    try:
        raise error
    except TelegramError:
        logging.getLogger(__name__).warning('TelegramError! %s caused by this update: %s', error, update)


active_polls = {}

class InvalidInput(Exception):
    pass

class Poll:
    def __init__(self, question, first_option):
        self.question = question
        self.options = [option]

    def add_vote(self, user, first_choices):
        self.votes[user] = Vote(first_choices)
        return self.votes[user]

    def call_election(self):
        # TODO actually implement ranked pairs
        return [{n} for n in range(self.n_options)]
        # desired output: ranking of all candidates (possibly with equalities)

class Vote:
    def __init__(self, n_options, first_choices):
        self.option_rankings = { i: 0 for i in range(n_options) }
        self.n_options = n_options

    def extend_vote(self, option, rank):
        if option < 0 or option >= n_options:
            raise InvalidInput("invalid option!")
        elif rank < 0 or rank > n_options:
            raise InvalidInput("invalid rank!")

        self.option_rankings[option] = n_options - rank

class DMType(Enum):
    UNKNOWN = 0
    CREATING = 1
    VOTING = 2

class CreationStatus(Enum):
    WAITING = 1
    WAITING_RESULT_TYPE = 2
    WRITING_QUESTION = 3
    WRITING_OPTION = 4
    MORE_OPTIONS = 5


def new_poll_handler(bot, update, chat_data):
    pass # TODO

def poll_done_handler(bot, update, chat_data):
    pass # TODO

def cancel_handler(bot, update, chat_data):
    pass # TODO

def message_handler(bot, update, chat_data):
    pass # TODO

# TODO more handlers for button presses


if __name__ == "__main__":
    updater = Updater(token=API_KEY)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(get_static_handler("start"))
    dispatcher.add_handler(CommandHandler('feedback', feedback_handler, pass_args=True))

    dispatcher.add_handler(CommandHandler('newpoll', new_poll_handler, pass_chat_data=True))
    dispatcher.add_handler(CommandHandler('done', new_poll_handler, pass_chat_data=True))
    dispatcher.add_handler(CommandHandler('cancel', cancel_handler, pass_chat_data=True))

    dispatcher.add_handler(MessageHandler(Filters.text, message_handler, pass_chat_data=True))

    dispatcher.add_error_handler(handle_error)

    # allows viewing of exceptions
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO) # not sure exactly how this works

    updater.start_polling()
    updater.idle()
