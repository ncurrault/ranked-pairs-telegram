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


class CallbackDataType(Enum):
    REFRESH = 0
    STARTING_VOTE = 1
    SELECTING_OPTION = 2
    SELECTING_RANK = 3
    SUBMITTING_VOTE = 4
    RETRACTING_VOTE = 5
    CLOSING_POLL = 6

# TODO telegram probably has a better way of passing data in a way that's under 64 bytes...
def encode_refresh(poll_id):
    return f"0:{poll_id}"
def encode_vote_start(poll_id):
    return f"1:{poll_id}"
def encode_option(poll_id, opt_idx):
    return f"2:{poll_id}:{opt_idx}"
def encode_rank(poll_id, rank):
    return f"3:{poll_id}:{rank}"
def encode_submit(poll_id):
    return f"4:{poll_id}"
def encode_retract(poll_id):
    return f"5:{poll_id}"
def encode_close(poll_id):
    return f"6:{poll_id}"

def decode_callback(s):
    if s[0] == "1":
        return CallbackDataType.STARTING_VOTE, s[2:]
    elif s[0] == "2":
        sep = s.rfind(":")
        return CallbackDataType.SELECTING_OPTION, s[2:sep], int(s[sep+1:])
    elif s[0] == "3":
        sep = s.rfind(":")
        return CallbackDataType.SELECTING_RANK, s[2:sep], int(s[sep+1:])
    elif s[0] == "4":
        return CallbackDataType.SUBMITTING_VOTE, s[2:]
    elif s[0] == "5":
        return CallbackDataType.RETRACTING_VOTE, s[2:]
    elif s[0] == "6":
        return CallbackDataType.CLOSING_POLL, s[2:]
    else:
        return (CallbackDataType.REFRESH,)

class Poll:
    def __init__(self, question, options, live_results):
        self.question = question
        self.live_results = live_results
        self.ongoing = True
        self.options = options
        self.votes = {}

        self.id = "dcb25d75-4e00-41a5-b673-4faf20427fc6" # str(uuid.uuid4()) # generate random id for each poll that's unreasonably hard to guess
        Poll.active_polls[self.id] = self

    active_polls = {}
    @classmethod
    def poll_of_id(cls, id):
        return Poll.active_polls.get(id)

    def get_short_description(self):
        poll_type = "live ranked-pairs poll" if self.live_results else "ranked-pairs poll with results at end"
        return poll_type + "\n" + " / ".join(self.options)
    def get_unstarted_vote_buttons(self):
        return telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton(text="Vote",
                callback_data=encode_vote_start(self.id))],
            [telegram.InlineKeyboardButton(text="Refresh Results", callback_data=encode_refresh(self.id))]
        ])
    def get_buttons(self, user):
        if user in self.votes:
            return self.votes[user].get_button_data()
        else:
            return self.get_unstarted_vote_buttons()

    def get_inline_result(self):
        return telegram.InlineQueryResultDocument(id=self.id,
            title=self.question, description=self.get_short_description(),
            input_message_content=telegram.InputTextMessageContent(message_text=self.get_long_html_str(), parse_mode=telegram.ParseMode.HTML),
            reply_markup=self.get_unstarted_vote_buttons(),
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

    def remove_vote(self, user):
        if user in self.votes:
            del self.votes[user]


    def call_election(self):
        # TODO actually implement ranked pairs
        return [0]
        # desired output for v1: just the winners
        # return [{n} for n in range(self.n_options)]
        # desired output: ranking of all candidates (possibly with equalities)

class Vote:
    def __init__(self, user, poll):
        self.poll = poll
        self.user = user
        self.n_options = len(poll.options)
        self.option_rankings = [0] * self.n_options

        self.finalized = False
        self.selected_option = None

    def __str__(self):
        return "\n".join([
            self.poll.options[i] + " - " + rank_to_str(self.option_rankings[i])
            for i in range(self.n_options)
        ])

    @classmethod
    def rank_to_str(cls, rank):
        if rank == 0:
            return "ABSTAIN"
        else:
            ones = rank % 10
            if ones == 1:
                return f"{rank}st"
            elif ones == 2:
                return f"{rank}nd"
            elif ones == 3:
                return f"{rank}rd"
            else:
                return f"{rank}th"

    def tap_option(self, option):
        if option < 0 or option >= self.n_options:
            raise InvalidInput("invalid option!")
        else:
            self.selected_option = option

    def tap_rank(self, rank):
        if rank < 0 or rank > self.n_options:
            raise InvalidInput("invalid rank!")
        if self.selected_option is None:
            raise InvalidInput("must select option before rank!")
        self.__set_ranking(self.selected_option, rank)
        self.selected_option = None

    def __set_ranking(self, option, rank):
        self.option_rankings[option] = rank

    def get_button_data(self):
        if self.finalized:
            return telegram.InlineKeyboardMarkup([
                [telegram.InlineKeyboardButton(text="Retract Vote", callback_data=encode_retract(self.poll.id))],
                [telegram.InlineKeyboardButton(text="Refresh Results", callback_data=encode_refresh(self.poll.id))]
            ])
        elif self.selected_option is None:
            rankings = list(map(Vote.rank_to_str, self.option_rankings))
            button_lst = [
                telegram.InlineKeyboardButton(text=f"{self.poll.options[i]} - {rankings[i]}", \
                callback_data=encode_option(self.poll.id, i)) \
                for i in range(self.n_options) ]
        else:
            option_str = self.poll.options[self.selected_option]
            button_lst = [ \
                telegram.InlineKeyboardButton(text=f"Rank {option_str} {Vote.rank_to_str(i)}", \
                callback_data=encode_rank(self.poll.id, i)) \
                for i in range(self.n_options + 1) ]
            button_lst.append( # button to keep current ranking, effectively going back
                telegram.InlineKeyboardButton(text=f"Back to option list",
                callback_data=encode_rank(self.poll.id, self.option_rankings[self.selected_option])))

        return telegram.InlineKeyboardMarkup([ [btn] for btn in button_lst ] +
            [[telegram.InlineKeyboardButton(text="Cancel", callback_data=encode_retract(self.poll.id)),
            telegram.InlineKeyboardButton(text="Refresh", callback_data=encode_refresh(self.poll.id)) ]])
            # always allow user to cancel vote

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
    poll = Poll("Question?", ["option 1", "option 2", "option 3"], True)
    if "active_polls" not in user_data:
        user_data["active_polls"] = set()

    user_data["active_polls"].add(poll)
    # TODO TESTING ONLY
    return

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
    out_polls = user_data.get("active_polls", [])
    output_options = [ poll.get_inline_result() for poll in out_polls ]
    bot.answer_inline_query(update.inline_query.id, results=output_options, is_personal=True)

def callback_handler(bot, update, user_data):
    print(update.callback_query)
    decoded_data = decode_callback(update.callback_query.data)
    req_type = decoded_data[0]
    poll = Poll.poll_of_id(decoded_data[1])
    user_id = update.callback_query.from_user.id

    print(decoded_data)

    if req_type == CallbackDataType.REFRESH:
        try:
            update.callback_query.edit_message_text(poll.get_long_html_str(), parse_mode=telegram.ParseMode.HTML)
        except TelegramError:
            pass # ignore error if message was not modified
    else:
        vote = poll.add_vote(user_id) # should generate vote if necessary

        if req_type == CallbackDataType.SELECTING_OPTION:
            opt = decoded_data[2]
            vote.tap_option(opt)
        elif req_type == CallbackDataType.SELECTING_RANK:
            rank = decoded_data[2]
            vote.tap_rank(rank)
        elif req_type == CallbackDataType.SUBMITTING_VOTE:
            vote.finalize()
        elif req_type == CallbackDataType.RETRACTING_VOTE:
            poll.remove_vote(user_id)
        elif req_type == CallbackDataType.CLOSING_POLL:
            pass # TODO required functionality not yet implemented

        update.callback_query.edit_message_reply_markup(reply_markup=poll.get_buttons(user_id))

    update.callback_query.answer()


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
