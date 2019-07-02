import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, \
    InlineQueryHandler, CallbackQueryHandler
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
    DM_URL = f"http://t.me/{USERNAME}"

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

class InvalidInput(Exception):
    pass

# TODO telegram probably has a better way of passing data in a way that's under 64 bytes...
def encode_callback(poll_id, option_idx, rank):
    assert len(poll_id) == 36
    option_idx = str(option_idx) if option_idx else ""
    rank = str(rank) if rank else ""

    return "{poll_id}:{option_idx}:{rank}"
def decode_callback(s):
    assert s.count(":") == 2
    id = s[:s.find(":")]
    option_idx = s[s.find(":") + 1: s.rfind(":")]
    rank = s[s.rfind(":") + 1 :]

    option_idx = int(option_idx) if option_idx.isdigit() else None
    rank = int(rank) if rank.isdigit() else None
    return id, option_idx, rank

class Poll:
    def __init__(self, question, options, live_results):
        self.question = question
        self.live_results = live_results
        self.ongoing = True
        self.options = options
        self.votes = {}

        self.id = str(uuid.uuid4()) # generate random id for each poll that's unreasonably hard to guess
        Poll.active_polls[self.id] = self

    active_polls = {}
    @classmethod
    def poll_of_id(cls, id):
        return active_polls.get(id)

    def get_short_description(self):
        poll_type = "live ranked-pairs poll" if self.live_results else "ranked-pairs poll with results at end"
        return poll_type + "\n" + " / ".join(self.options)
    def get_vote_button(self):
        return telegram.InlineKeyboardButton(text="Vote",
            callback_data=encode_callback(self.id, None, None))

    def get_inline_result(self):
        return telegram.InlineQueryResultDocument(id=self.id,
            title=self.question, description=self.get_short_description(),
            input_message_content=telegram.InputTextMessageContent(message_text=self.get_long_html_str(), parse_mode=telegram.ParseMode.HTML),
            reply_markup=telegram.InlineKeyboardMarkup(inline_keyboard=[[ self.get_vote_button() ]]),
            mime_type="application/zip", document_url=DM_URL) # URL actually only used to generate the preview
    def get_long_html_str(self):
        """
        Get representation of a poll: question, options, result type, whether poll is ongoing
        """
        poll_type = "live ranked-pairs poll" if self.live_results else "ranked-pairs poll with results at end"
        option_lines = '\n'.join( map(lambda o: f"▫️ {o}\n", self.options) ) # TODO indicate winners when appropriate
        poll_status = "ongoing poll" if self.ongoing else "closed poll"
        # TODO last updated when

        return f"<b>{self.question}</b>\n" + \
            f"<i>{poll_type}</i>\n\n" + \
            option_lines + \
            f"\n<i>{poll_status}</i>"
        # TODO checked boxes next to winner(s)

    def add_vote(self, user):
        if user not in self.votes:
            self.votes[user] = Vote(user, self)
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
        self.n_options = len(poll.options)
        self.option_rankings = [0] * self.n_options
        self.current_rank = 1
        self.finalized = False

    def inc_current_rank(self):
        self.current_rank = (self.current_rank + 1) % self.n_options

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
        user_data["create_status"] = CreationStatus.CHOOSING_RESULT_TYPE
        keyboard_options = telegram.ReplyKeyboardMarkup(keyboard=[["Live Results", "When Closed"]], resize_keyboard=True)

        bot.send_message(chat_id=update.message.chat.id,
            text="Let's make a ranked-pairs poll! Send /cancel at any time to stop.")
        bot.send_message(chat_id=update.message.chat.id,
            text="Would you like the poll results to appear live or only when it is closed?",
            reply_markup=keyboard_options)
    else:
        update.message.reply_markdown(text=f"Don't spam this chat, [slide into my DMs]({DM_URL}) to start a poll.")

def poll_done_handler(bot, update, user_data):
    status = user_data.get("create_status")
    if status == CreationStatus.WRITING_OPTIONS:
        if len(user_data["pending_options"]) >= 2:
            poll = Poll(user_data["pending_question"],
                user_data["pending_options"], user_data["pending_results_live"])

            bot.send_message(chat_id=update.message.chat.id,
                text="Successfully created poll!")
            bot.send_message(chat_id=update.message.chat.id,
                text=poll.get_long_html_str(), parse_mode=telegram.ParseMode.HTML)
            # TODO buttons for closing, sharing, update (if live)

            if "active_polls" not in user_data:
                user_data["active_polls"] = set()

            user_data["active_polls"].add(poll)
            # bot.send_message(chat_id=update.message.chat.id,
            #     text=str(poll), parse_mode=telegram.ParseMode.HTML,
            #     reply_markup=telegram.InlineKeyboardMarkup([
            #         [ telegram.InlineKeyboardButton(text="A", callback_data="a") ],
            #         [ telegram.InlineKeyboardButton(text="B", callback_data="b") ],
            #         [ telegram.InlineKeyboardButton(text="C", callback_data="c") ],
            #         [ telegram.InlineKeyboardButton(text="Cancel Vote", callback_data="cancel") ],
            #     ]))

            # TODO inline interface to show a summary of options, share, and close

            user_data["create_status"] = CreationStatus.WAITING # now waiting for another poll

            return
        else:
            reason = "write at least two options"
    elif status == CreationStatus.CHOOSING_RESULT_TYPE:
        reason = "chose a result type"
    elif status == CreationStatus.WRITING_QUESTION:
        reason = "write a question"
    else:
        reason = "start a poll with /start"

    bot.send_message(chat_id=update.message.chat.id,
        text=f"Cannot create poll. Please {reason}!")

def cancel_handler(bot, update, user_data):
    if user_data.get("create_status") != CreationStatus.WAITING:
        user_data["create_status"] = CreationStatus.WAITING

        bot.send_message(chat_id=update.message.chat.id,
            text="Cancelled! /start to try again",
            reply_markup=telegram.ReplyKeyboardRemove())

def message_handler(bot, update, user_data):
    if "create_status" in user_data:
        if user_data["create_status"] == CreationStatus.CHOOSING_RESULT_TYPE:
            if update.message.text in ("Live Results", "When Closed"):
                user_data["pending_results_live"] = update.message.text == "Live Results"
                user_data["create_status"] = CreationStatus.WRITING_QUESTION

                bot.send_message(chat_id=update.message.chat.id,
                    text="Great! Now send the question for your poll",
                    reply_markup=telegram.ReplyKeyboardRemove())
            else:
                update.message.reply_text("Please reply using the buttons")
                return
            # reply_markup=telegram.ReplyKeyboardRemove()
        elif user_data["create_status"] == CreationStatus.WRITING_QUESTION:
            user_data["create_status"] = CreationStatus.WRITING_OPTIONS
            user_data["pending_question"] = update.message.text
            user_data["pending_options"] = []
            bot.send_message(chat_id=update.message.chat.id,
                text="Great! Now send the first option")
        elif user_data["create_status"] == CreationStatus.WRITING_OPTIONS:
            user_data["pending_options"].append(update.message.text)
            msg = "Great! Now send another option"
            if len(user_data["pending_options"]) >= 2:
                msg = msg + " (or /done if there are no more options)"
            bot.send_message(chat_id=update.message.chat.id, text=msg)

def inline_query_handler(bot, update, user_data):
    # TODO sample poll for testing
    out_polls = [Poll("Question?", ["option 1", "option 2", "option 3"], True)] #user_data.get("active_polls", [])
    output_options = [ poll.get_inline_result() for poll in out_polls ]
    bot.answer_inline_query(update.inline_query.id, results=output_options, is_personal=True)

def callback_handler(bot, update, user_data):
    print(update.callback_query)
    # TODO


if __name__ == "__main__":
    updater = Updater(token=API_KEY)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(get_static_handler("help"))
    dispatcher.add_handler(CommandHandler('feedback', feedback_handler, pass_args=True))

    dispatcher.add_handler(CommandHandler('start', new_poll_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('done', poll_done_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('cancel', cancel_handler, pass_user_data=True))

    dispatcher.add_handler(MessageHandler(Filters.text, message_handler, pass_user_data=True))

    dispatcher.add_handler(InlineQueryHandler(inline_query_handler, pass_user_data=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_handler, pass_user_data=True))

    dispatcher.add_error_handler(handle_error)

    # allows viewing of exceptions
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO) # not sure exactly how this works

    updater.start_polling()
    updater.idle()
