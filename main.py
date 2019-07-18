import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, \
    InlineQueryHandler, CallbackQueryHandler
from telegram.error import TelegramError
import ranked_pairs

import logging

import datetime
import uuid
import sys
import os
import time
from enum import Enum

with open("data/token.txt", "r") as f:
    API_KEY = f.read().rstrip()

with open("data/username.txt", "r") as f:
    USERNAME = f.read().rstrip()
    DM_URL = "http://t.me/" + USERNAME

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
    REFRESH_ADMIN = 7
    # TODO delete poll?

# TODO telegram probably has a better way of passing data in a way that's under 64 bytes...
def encode_refresh(poll_id):
    return "0:" + poll_id
def encode_refresh_admin(poll_id):
    return "7:" + poll_id
def encode_vote_start(poll_id):
    return "1:" + poll_id
def encode_option(poll_id, opt_idx):
    return "2:" + poll_id + ":" + str(opt_idx)
def encode_rank(poll_id, rank):
    return "3:" + poll_id + ":" + str(rank)
def encode_submit(poll_id):
    return "4:" + poll_id
def encode_retract(poll_id):
    return "5:" + poll_id
def encode_close(poll_id):
    return "6:" + poll_id

def decode_callback(s):
    if s[0] == "0":
        return CallbackDataType.REFRESH, s[2:]
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
    elif s[0] == "7":
        return CallbackDataType.REFRESH_ADMIN, s[2:]
    else:
        raise InvalidInput("unknown callback: " + str(s))

class Poll:
    def __init__(self, question, options, live_results, owner):
        self.question = question
        self.live_results = live_results
        self.owner = owner
        self.ongoing = True
        self.options = options
        self.votes = {}

        self.option_ranks = [1] * len(options)

        self.id = str(uuid.uuid4()) # generate random id for each poll that's unreasonably hard to guess
        Poll.active_polls[self.id] = self

    active_polls = {}
    @classmethod
    def poll_of_id(cls, id):
        return Poll.active_polls.get(id)

    def get_public_buttons(self):
        if not self.ongoing:
            return telegram.InlineKeyboardMarkup([[]])

        return telegram.InlineKeyboardMarkup([
            [telegram.InlineKeyboardButton(text="Vote",
                callback_data=encode_vote_start(self.id))],
            [telegram.InlineKeyboardButton(text="Refresh Results", callback_data=encode_refresh(self.id))]
        ])
    def get_admin_buttons(self):
        if not self.ongoing:
            return telegram.InlineKeyboardMarkup([[]])

        return telegram.InlineKeyboardMarkup([ # TODO support poll title in inline query and pass it here
            [telegram.InlineKeyboardButton(text="Close Poll", callback_data=encode_close(self.id))],
            [telegram.InlineKeyboardButton(text="Refresh Results", callback_data=encode_refresh_admin(self.id))],
            [telegram.InlineKeyboardButton(text="Share Poll", switch_inline_query=""),
            telegram.InlineKeyboardButton(text="Vote", callback_data=encode_vote_start(self.id))]
        ])

    def get_inline_result(self):
        """
        Content that users will send to others to allow them to cast votes
        """
        return telegram.InlineQueryResultDocument(id=self.id,
            title=self.question,
            description=("live ranked-pairs poll" if self.live_results else "ranked-pairs poll with results at end") + "\n" + " / ".join(self.options),
            input_message_content=telegram.InputTextMessageContent(message_text=self.get_html_repr(), parse_mode=telegram.ParseMode.HTML),
            reply_markup=self.get_public_buttons(),
            mime_type="application/zip", document_url=DM_URL) # URL actually only used to generate the preview
    def get_html_repr(self):
        """
        Get representation of a poll: question, options, result type, whether poll is ongoing
        """
        poll_type = "live ranked-pairs poll" if self.live_results else "ranked-pairs poll with results at end"

        def option_to_line(option_index, option):
            if self.live_results or not self.ongoing:
                return str(self.option_ranks[option_index]) + ". " + option
            else:
                return "- " + str(option)

        option_lines = list(map(lambda t: option_to_line(*t), enumerate(self.options) ))
        option_lines.sort()
        option_lines_str = '\n'.join( option_lines )


        poll_status = "ongoing poll" if self.ongoing else "closed poll"
        last_update_str = datetime.datetime.strftime(datetime.datetime.now(), '%c')

        n_votes = sum(vote.status == VoteStatus.COUNTED for vote in self.votes.values())
        n_drafts = sum(vote.status == VoteStatus.IN_PROGRESS for vote in self.votes.values())

        return "<b>" + self.question + "</b>\n" + \
            "<i>" + poll_type + "</i>\n\n" + \
            option_lines_str + \
            "\n<i>" + poll_status + "</i>\n" + \
            str(n_votes) + " votes submitted, " + str(n_drafts) + " ballot drafts" + \
            "\n\nLast updated: " + last_update_str + \
            '\nP.S. you have to have <a href="' + DM_URL + '">DM\'d me</a> before voting'

    def send_to_owner(self, bot):
        bot.send_message(chat_id=self.owner,
            text=self.get_html_repr(), parse_mode=telegram.ParseMode.HTML,
            reply_markup=self.get_admin_buttons())

    def add_vote(self, user):
        if user not in self.votes:
            self.votes[user] = Vote(user, self)
        return self.votes[user]

    def remove_vote(self, user):
        if user in self.votes:
            del self.votes[user]

    def call_election(self):
        ballots = [
            vote.mapped_option_rankings for vote in self.votes.values()
            if vote.status == VoteStatus.COUNTED
        ]
        if len(ballots) > 0:
            self.option_ranks = ranked_pairs.get_candidate_rankings(ballots)
        else:
            self.option_ranks = [1] * len(self.options)

    def update_winners_if_live(self):
        if self.live_results:
            self.call_election()

    def close(self):
        self.ongoing = False
        self.call_election()

class VoteStatus(Enum):
    IN_PROGRESS = 1
    COUNTED = 2
    LATE = 3

class Vote:
    def __init__(self, user, poll):
        self.poll = poll
        self.user = user
        self.n_options = len(poll.options)
        self.option_rankings = [0] * self.n_options

        self.ballot_message = None
        self.status = VoteStatus.IN_PROGRESS

        self.selected_option = None

    def retract_vote(self):
        self.poll.remove_vote(self.user)
        if self.ballot_message:
            self.ballot_message.delete()

    @classmethod
    def rank_to_str(cls, rank):
        if rank == 0:
            return "ABSTAIN"
        else:
            ones = rank % 10
            if ones == 1:
                return str(rank) + "st"
            elif ones == 2:
                return str(rank) + "nd"
            elif ones == 3:
                return str(rank) + "rd"
            else:
                return str(rank) + "th"

    def get_ballot_html(self):
        current_rankings = []
        for i in range(self.n_options):
            s = self.poll.options[i] + " - "
            if i == self.selected_option:
                s += "SELECT A RANK"
            else:
                s += Vote.rank_to_str(self.option_rankings[i])
            current_rankings.append(s)

        ballot_draft = "\n".join(current_rankings)
        worst_rank = Vote.rank_to_str(self.n_options)

        if self.status == VoteStatus.IN_PROGRESS:
            status = "ballot draft"

            if self.selected_option is None:
                instructions = "If this ballot looks good, click \"Submit Vote.\" Otherwise, click the button corresponding to the option whose rank you would like to change. You can also click \"Cancel Vote\" to delete this ballot."
            else:
                instructions = "Click the rank you would like to assign to " + self.poll.options[self.selected_option] + ". You can also click \"Cancel Vote\" to delete this ballot."
        elif self.status == VoteStatus.COUNTED:
            status = "submitted ballot"
            instructions = "To delete this ballot, use the \"Retract Vote\" button"
        elif self.status == VoteStatus.LATE:
            status = "late ballot"
            instructions = "The poll creator closed this poll before you submitted your ballot, so this vote cannot be counted"

        return "This is a <b>ranked-pairs ballot</b>. " + \
            "In this system <b>votes are ranked</b>, " + \
            "so you vote by giving each of the options a rank between 1 and " + str(self.n_options) + ", inclusive, or ABSTAIN. " + \
            "(1st = good, " + str(worst_rank) + "= bad, ABSTAIN = even worse than " + str(worst_rank) + ".) " + \
            "\n\n<b>{self.poll.question}</b>\n{ballot_draft}" + \
            "\n\n<i>Ballot status: " + status + "</i>\n" + instructions

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
        if self.status != VoteStatus.IN_PROGRESS:
            return telegram.InlineKeyboardMarkup([[
                telegram.InlineKeyboardButton(text="Retract Vote", callback_data=encode_retract(self.poll.id))
            ]])
        elif self.selected_option is None:
            rankings = list(map(Vote.rank_to_str, self.option_rankings))
            button_lst = [
                telegram.InlineKeyboardButton(text="Rank " + self.poll.options[i], \
                callback_data=encode_option(self.poll.id, i)) \
                for i in range(self.n_options) ]
            button_lst.append( # button to keep current ranking, effectively going back
                telegram.InlineKeyboardButton(text="Submit Vote",
                callback_data=encode_submit(self.poll.id)))
        else:
            option_str = self.poll.options[self.selected_option]
            button_lst = [ \
                telegram.InlineKeyboardButton(text="Rank " + option_str + " as " + Vote.rank_to_str(i), \
                callback_data=encode_rank(self.poll.id, i)) \
                for i in range(self.n_options + 1) ]
            button_lst.append( # button to keep current ranking, effectively going back
                telegram.InlineKeyboardButton(text="Back to option list",
                callback_data=encode_rank(self.poll.id, self.option_rankings[self.selected_option])))

        return telegram.InlineKeyboardMarkup([ [btn] for btn in button_lst ] + [[
            telegram.InlineKeyboardButton(text="Cancel Vote", callback_data=encode_retract(self.poll.id))
        ]]) # always allow user to cancel vote

    def send_ballot(self, bot):
        if self.ballot_message is not None:
            self.ballot_message.delete() # only one ballot at a time

        self.ballot_message = bot.send_message(chat_id=self.user,
            text=self.get_ballot_html(),
            parse_mode=telegram.ParseMode.HTML,
            reply_markup=self.get_button_data())

    def update_ballot(self):
        if self.ballot_message is not None:
            try:
                self.ballot_message.edit_text( \
                    text=self.get_ballot_html(), parse_mode=telegram.ParseMode.HTML,
                    reply_markup=self.get_button_data())
            except TelegramError:
                pass # ignore error if message was not modified

    def finalize(self):
        if self.poll.ongoing:
            self.status = VoteStatus.COUNTED
        else:
            self.status = VoteStatus.LATE

        # map inputs to form expected by ranked pairs implementation
        self.mapped_option_rankings = [ \
            self.n_options - rank if rank > 0 else 0 \
            for rank in self.option_rankings \
        ]

        self.poll.update_winners_if_live()

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
        update.message.reply_markdown(text="Don't spam this chat, [slide into my DMs](" + DM_URL + ") to start a poll.")

def poll_done_handler(bot, update, user_data):
    if "active_polls" not in user_data:
        user_data["active_polls"] = set()

    status = user_data.get("create_status")
    if status == CreationStatus.WRITING_OPTIONS:
        if len(user_data["pending_options"]) >= 2:
            poll = Poll(user_data["pending_question"],
                user_data["pending_options"], user_data["pending_results_live"],
                update.message.from_user.id)

            bot.send_message(chat_id=update.message.chat.id,
                text="Successfully created poll!")
            poll.send_to_owner(bot)

            if "active_polls" not in user_data:
                user_data["active_polls"] = set()

            user_data["active_polls"].add(poll)

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
        text="Cannot create poll. Please " + reason + "!")

def cancel_handler(bot, update, user_data):
    if user_data.get("create_status") != CreationStatus.WAITING:
        user_data["create_status"] = CreationStatus.WAITING

        bot.send_message(chat_id=update.message.chat.id,
            text="Cancelled! /newpoll to try again",
            reply_markup=telegram.ReplyKeyboardRemove())

def poll_list_handler(bot, update, user_data):
    if update.message.chat.type == "private":
        polls = user_data.get("active_polls", [])
        if len(polls) == 0:
            update.message.reply_text(text="You don't seem to have any active polls! You can make one with /newpoll")
        else:
            update.message.reply_text(text="You have " + str(len(polls)) + " polls! Here they are:")
            for poll in polls:
                poll.send_to_owner(bot)
    else:
        update.message.reply_markdown(text="Don't spam this chat, [slide into my DMs](" + DM_URL + ") to use this command.")

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
    out_polls = user_data.get("active_polls", [])
    output_options = [ poll.get_inline_result() for poll in out_polls ]
    bot.answer_inline_query(update.inline_query.id, results=output_options, is_personal=True)

def callback_handler(bot, update, user_data):
    decoded_data = decode_callback(update.callback_query.data)
    req_type = decoded_data[0]
    poll = Poll.poll_of_id(decoded_data[1])
    user_id = update.callback_query.from_user.id

    if req_type == CallbackDataType.CLOSING_POLL:
        poll.close()
        req_type = CallbackDataType.REFRESH_ADMIN
        # FIXME closing a poll should also trigger a refresh but this seems messy

    if req_type == CallbackDataType.REFRESH:
        try:
            update.callback_query.edit_message_text(poll.get_html_repr(), parse_mode=telegram.ParseMode.HTML,
                reply_markup=poll.get_public_buttons())
        except TelegramError:
            pass # ignore error if message was not modified
    elif req_type == CallbackDataType.REFRESH_ADMIN:
        try:
            update.callback_query.edit_message_text(poll.get_html_repr(), parse_mode=telegram.ParseMode.HTML,
                reply_markup=poll.get_admin_buttons())
        except TelegramError:
            pass # ignore error if message was not modified
    else:
        vote = poll.add_vote(user_id) # should generate vote if necessary

        if req_type == CallbackDataType.STARTING_VOTE:
            vote.send_ballot(bot)
        elif req_type == CallbackDataType.SELECTING_OPTION:
            opt = decoded_data[2]
            vote.tap_option(opt)
        elif req_type == CallbackDataType.SELECTING_RANK:
            rank = decoded_data[2]
            vote.tap_rank(rank)
        elif req_type == CallbackDataType.SUBMITTING_VOTE:
            vote.finalize()
        elif req_type == CallbackDataType.RETRACTING_VOTE:
            vote.retract_vote()

        vote.update_ballot()

    update.callback_query.answer()


if __name__ == "__main__":
    # TODO persistence (as soon as it's out of beta)

    updater = Updater(token=API_KEY)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(get_static_handler("help"))
    dispatcher.add_handler(CommandHandler('feedback', feedback_handler, pass_args=True))

    dispatcher.add_handler(CommandHandler('newpoll', new_poll_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('done', poll_done_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('mypolls', poll_list_handler, pass_user_data=True))
    dispatcher.add_handler(CommandHandler('cancel', cancel_handler, pass_user_data=True))

    dispatcher.add_handler(MessageHandler(Filters.text, message_handler, pass_user_data=True))

    dispatcher.add_handler(InlineQueryHandler(inline_query_handler, pass_user_data=True))
    dispatcher.add_handler(CallbackQueryHandler(callback_handler, pass_user_data=True))

    dispatcher.add_error_handler(handle_error)

    # allows viewing of exceptions
    logging.basicConfig(
        filename="data/bot.log",
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO) # not sure exactly how this works

    updater.start_polling()
    updater.idle()
