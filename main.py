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

with open("data/username.txt", "r") as f:
    USERNAME = f.read().rstrip()

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
        feedback = open("data/feedback.txt", "a")
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
        logging.getLogger(__name__).warning('TelegramError! %s caused by this update:\n%s', error, update)


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
        return [0]
        # desired output for v1: just the winners
        # return [{n} for n in range(self.n_options)]
        # desired output: ranking of all candidates (possibly with equalities)

class Vote:
    def __init__(self, user, poll):
        self.poll = poll
        self.option_rankings = [0] * len(poll.options)
        self.current_rank = 1
        self.finalized = False

    def inc_current_rank(self):
        self.current_rank = (self.current_rank + 1) % len(poll.options)

    def toggle_ranking(self, option):
        if option < 0 or option >= n_options:
            raise InvalidInput("invalid option!")

        if self.option_rankings[option] == self.current_rank:
            self.option_rankings[option] = 0
        else:
            self.option_rankings[option] = self.current_rank

    def finalize(self):
        if self.finalized:
            raise InvalidInput("Vote already finalized!")

        self.finalized = True
        self.option_rankings = [ \
            len(poll.options) - rank if rank > 0 else 0 \
            for rank in option_rankings \
        ]

class CreationStatus(Enum):
    WAITING = 1
    CHOOSING_RESULT_TYPE = 2
    WRITING_QUESTION = 3
    WRITING_OPTIONS = 4


def new_poll_handler(bot, update, user_data):
    if update.message.chat.type == "private":
        bot.send_message(chat_id=update.message.chat.id,
            text="Let's make a ranked-pairs poll! Send /cancel at any time to stop.")
        bot.send_message(chat_id=update.message.chat.id,
            text="Would you like the poll results to appear live or only when it is closed?")
        # TODO custom keyboard replies: "Live Results" or "When Closed"

        chat_data["create_status"] = CreationStatus.CHOOSING_RESULT_TYPE
    else:
        update.message.reply_markdown(text=f"Don't spam this chat, [slide into my DMs](t.me/{USERNAME}) to start a poll.")

def poll_done_handler(bot, update, user_data):
    pass # TODO

def cancel_handler(bot, update, user_data):
    pass # TODO

def message_handler(bot, update, user_data):
    pass # TODO

# TODO more handlers for button presses


if __name__ == "__main__":
    updater = Updater(token=API_KEY)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(get_static_handler("help"))
    dispatcher.add_handler(CommandHandler('feedback', feedback_handler, pass_args=True))

    dispatcher.add_handler(CommandHandler('start', new_poll_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('done', new_poll_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('cancel', cancel_handler, pass_user_data=True))

    dispatcher.add_handler(MessageHandler(Filters.text, message_handler, pass_user_data=True))

    dispatcher.add_error_handler(handle_error)

    # allows viewing of exceptions
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO) # not sure exactly how this works

    updater.start_polling()
    updater.idle()
