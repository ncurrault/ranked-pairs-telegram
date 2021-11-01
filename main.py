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

API_KEY = os.environ["BOT_TOKEN"]
USERNAME = os.environ["BOT_USERNAME"]
DM_URL = "https://t.me/{}".format(USERNAME[1:])

PORT = os.environ.get("PORT", 80)

def get_static_handler(command):
    """
    Given a string command, returns a CommandHandler for that string that
    responds to messages with the content of static_responses/[command].txt

    Throws IOError if file does not exist or something
    """

    f = open("static_responses/{}.txt".format(command), "r")
    response = f.read()

    return CommandHandler(command, \
        ( lambda update, context : \
        context.bot.send_message(chat_id=update.message.chat.id, text=response) ) )

def handle_error(update, context):
    logging.getLogger(__name__).warning('Error %s caused by this update:\n%s', context.error, update)

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
    CHANGE_OF_RANK = 8
    # TODO delete poll?

# TODO telegram probably has a better way of passing data in a way that's under 64 bytes...
def encode_refresh(poll_id):
    return "0:{}".format(poll_id)
def encode_refresh_admin(poll_id):
    return "7:{}".format(poll_id)
def encode_vote_start(poll_id):
    return "1:{}".format(poll_id)
def encode_option(poll_id, opt_idx):
    return "2:{}:{}".format(poll_id, opt_idx)
def encode_rank(poll_id, rank):
    return "3:{}:{}".format(poll_id, rank)
def encode_submit(poll_id):
    return "4:{}".format(poll_id)
def encode_retract(poll_id):
    return "5:{}".format(poll_id)
def encode_close(poll_id):
    return "6:{}".format(poll_id)
def encode_rank_change(poll_id):
    return "8:{}".format(poll_id)

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
    elif s[0] == "8":
        return CallbackDataType.CHANGE_OF_RANK, s[2:]
    else:
        raise InvalidInput("unknown callback: {}".format(s))

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

        if self.live_results or not self.ongoing:
            sorted_option_index = sorted(range(len(self.options)),
                key=lambda idx: self.option_ranks[idx])
            option_lines_str = "\n".join(map(lambda idx:
                "• {} ({})".format( self.options[idx],
                Vote.rank_to_str(self.option_ranks[idx]) ),
                sorted_option_index))
        else:
            option_lines_str = '\n'.join( "• " + opt for opt in self.options)

        poll_status = "ongoing poll" if self.ongoing else "closed poll"
        last_update_str = datetime.datetime.strftime(datetime.datetime.now(), '%c')

        n_votes = sum(vote.status == VoteStatus.COUNTED for vote in self.votes.values())
        n_drafts = sum(vote.status == VoteStatus.IN_PROGRESS for vote in self.votes.values())

        return ("<b>{}</b>\n" + \
            "<i>{}</i>\n\n" + \
            option_lines_str + \
            "\n\n<i>{}</i>" + \
            "\n{} votes submitted, {} ballot drafts" + \
            "\n\nLast updated: {}" + \
            '\nP.S. you have to have <a href="{}">DM\'d me</a> before voting') \
                .format(self.question, poll_type, poll_status, n_votes, n_drafts, last_update_str, DM_URL)

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
        self.update_winners_if_live()

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
    RETRACTED_LATE = 4

class Vote:
    def __init__(self, user, poll):
        self.poll = poll
        self.user = user
        self.n_options = len(poll.options)
        self.option_rankings = [0] * self.n_options

        self.ballot_message = None
        self.status = VoteStatus.IN_PROGRESS

        self.current_rank = 1

    def retract_vote(self):
        if self.poll.ongoing:
            self.poll.remove_vote(self.user)
            if self.ballot_message:
                self.ballot_message.delete()
        else:
            self.status = VoteStatus.RETRACTED_LATE

    @classmethod
    def rank_to_str(cls, rank):
        if rank == 0:
            return "ABSTAIN"
        else:
            ones = rank % 10
            tens = (rank // 10) % 100
            if ones == 1 and tens != 1:
                return "{}st".format(rank)
            elif ones == 2 and tens != 1:
                return "{}nd".format(rank)
            elif ones == 3 and tens != 1:
                return "{}rd".format(rank)
            else:
                return "{}th".format(rank)

    def get_ballot_html(self):
        ballot_draft = "\n".join( \
            self.poll.options[i] + " - " + Vote.rank_to_str(self.option_rankings[i]) \
            for i in range(self.n_options))
        worst_rank = Vote.rank_to_str(self.n_options)

        if self.status == VoteStatus.IN_PROGRESS:
            status = "ballot draft"
            if self.current_rank is None:
                instructions = "Select a rank you would like to assign to an option."
            else:
                instructions = ("Click the option you would like to rank <b>{}</b>.\n\n" \
                    + "You can also use <i>Change Rank</i> to jump to another rank (to correct mistakes, encode ties, or skip ranks)." \
                    ).format(Vote.rank_to_str(self.current_rank))
            instructions += " Click <i>Cancel Vote</i> to delete this ballot or <i>Submit Vote</i> to submit it as-is at any time."
        elif self.status == VoteStatus.COUNTED:
            status = "submitted ballot"
            instructions = "To delete this ballot, use the \"Retract Vote\" button"
        elif self.status == VoteStatus.LATE:
            status = "late ballot"
            instructions = "The poll creator closed this poll before you submitted your ballot, so this vote cannot be counted"
        elif self.status == VoteStatus.RETRACTED_LATE:
            status = "late-retracted ballot"
            instructions = "The poll creator closed this poll before you attempted to retract your ballot, so this vote was already counted"

        return ("This is a <b>ranked-pairs ballot</b>. " + \
            "In this system <b>votes are ranked</b>, " + \
            "so you vote by giving each of the options a rank between 1 and {}, inclusive, or ABSTAIN. " + \
            "(1st = good, {} = bad, ABSTAIN = even worse than {}.) " + \
            "\n\n<b>{}</b>\n{}" + \
            "\n\n<i>Ballot status: {}</i>\n{}") \
            .format(self.n_options, worst_rank, worst_rank, self.poll.question, ballot_draft, status, instructions)

    def tap_option(self, option):
        if option < 0 or option >= self.n_options:
            raise InvalidInput("invalid option!")
        else:
            self.__set_ranking(option, self.current_rank)

            if self.current_rank > 0:
                self.current_rank = (self.current_rank + 1) % (self.n_options + 1)

    def tap_rank(self, rank):
        if rank < 0 or rank > self.n_options:
            raise InvalidInput("invalid rank!")

        self.current_rank = rank

    def clear_current_ranking(self):
        self.current_rank = None

    def __set_ranking(self, option, rank):
        self.option_rankings[option] = rank

    def get_button_data(self):
        if self.status == VoteStatus.COUNTED:
            return telegram.InlineKeyboardMarkup([[
                telegram.InlineKeyboardButton(text="Retract Vote", callback_data=encode_retract(self.poll.id))
            ]])
        elif self.status == VoteStatus.IN_PROGRESS:
            if self.current_rank is None:
                button_lst = [ \
                    telegram.InlineKeyboardButton(text=Vote.rank_to_str(i), \
                    callback_data=encode_rank(self.poll.id, i)) \
                    for i in range(self.n_options + 1) ]
            else:
                rankings = list(map(Vote.rank_to_str, self.option_rankings))
                button_lst = [
                    telegram.InlineKeyboardButton(text=self.poll.options[i], \
                    callback_data=encode_option(self.poll.id, i)) \
                    for i in range(self.n_options) ]

                button_lst.append(
                    telegram.InlineKeyboardButton(text="Change Rank",
                    callback_data=encode_rank_change(self.poll.id)))

            return telegram.InlineKeyboardMarkup([ [btn] for btn in button_lst ] + [[
                telegram.InlineKeyboardButton(text="Cancel Vote", callback_data=encode_retract(self.poll.id)),
                telegram.InlineKeyboardButton(text="Submit Vote", callback_data=encode_submit(self.poll.id))
            ]]) # always allow user to submit, cancel vote
        else:
            return telegram.InlineKeyboardMarkup([[]])

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

def new_poll_handler(update, context):
    if update.message.chat.type == "private":
        context.user_data["create_status"] = CreationStatus.CHOOSING_RESULT_TYPE
        keyboard_options = telegram.ReplyKeyboardMarkup(keyboard=[["Live Results", "When Closed"]], resize_keyboard=True)

        context.bot.send_message(chat_id=update.message.chat.id,
            text="Let's make a ranked-pairs poll! Send /cancel at any time to stop.")
        context.bot.send_message(chat_id=update.message.chat.id,
            text="Would you like the poll results to appear live or only when it is closed?",
            reply_markup=keyboard_options)
    else:
        update.message.reply_markdown(text="Don't spam this chat, [slide into my DMs]({}) to start a poll.".format(DM_URL))

def poll_done_handler(update, context):
    if "active_polls" not in context.user_data:
        context.user_data["active_polls"] = set()

    status = context.user_data.get("create_status")
    if status == CreationStatus.WRITING_OPTIONS:
        if len(context.user_data["pending_options"]) >= 2:
            poll = Poll(context.user_data["pending_question"],
                context.user_data["pending_options"], context.user_data["pending_results_live"],
                update.message.from_user.id)

            context.bot.send_message(chat_id=update.message.chat.id,
                text="Successfully created poll!")
            poll.send_to_owner(context.bot)

            if "active_polls" not in context.user_data:
                context.user_data["active_polls"] = set()

            context.user_data["active_polls"].add(poll)

            context.user_data["create_status"] = CreationStatus.WAITING # now waiting for another poll

            return
        else:
            reason = "write at least two options"
    elif status == CreationStatus.CHOOSING_RESULT_TYPE:
        reason = "chose a result type"
    elif status == CreationStatus.WRITING_QUESTION:
        reason = "write a question"
    else:
        reason = "start a poll with /newpoll"

    context.bot.send_message(chat_id=update.message.chat.id,
        text="Cannot create poll. Please {}!".format(reason))

def cancel_handler(update, context):
    if context.user_data.get("create_status") != CreationStatus.WAITING:
        context.user_data["create_status"] = CreationStatus.WAITING

        context.bot.send_message(chat_id=update.message.chat.id,
            text="Cancelled! /newpoll to try again",
            reply_markup=telegram.ReplyKeyboardRemove())

def poll_list_handler(update, context):
    if update.message.chat.type == "private":
        polls = context.user_data.get("active_polls", [])
        if len(polls) == 0:
            update.message.reply_text(text="You don't seem to have any polls! You can make one with /newpoll")
        else:
            update.message.reply_text(text="You have {} polls! Here they are:".format(len(polls)))
            for poll in polls:
                poll.send_to_owner(context.bot)
    else:
        update.message.reply_markdown(text="Don't spam this chat, [slide into my DMs]({}) to use this command.".format(DM_URL))

def message_handler(update, context):
    if "create_status" in context.user_data:
        if context.user_data["create_status"] == CreationStatus.CHOOSING_RESULT_TYPE:
            if update.message.text in ("Live Results", "When Closed"):
                context.user_data["pending_results_live"] = update.message.text == "Live Results"
                context.user_data["create_status"] = CreationStatus.WRITING_QUESTION

                context.bot.send_message(chat_id=update.message.chat.id,
                    text="Great! Now send the question for your poll",
                    reply_markup=telegram.ReplyKeyboardRemove())
            else:
                update.message.reply_text("Please reply using the buttons")
                return
            # reply_markup=telegram.ReplyKeyboardRemove()
        elif context.user_data["create_status"] == CreationStatus.WRITING_QUESTION:
            context.user_data["create_status"] = CreationStatus.WRITING_OPTIONS
            context.user_data["pending_question"] = update.message.text
            context.user_data["pending_options"] = []
            context.bot.send_message(chat_id=update.message.chat.id,
                text="Great! Now send the first option")
        elif context.user_data["create_status"] == CreationStatus.WRITING_OPTIONS:
            context.user_data["pending_options"].append(update.message.text)
            msg = "Great! Now send another option"
            if len(context.user_data["pending_options"]) >= 2:
                msg = msg + " (or /done if there are no more options)"
            context.bot.send_message(chat_id=update.message.chat.id, text=msg)

def inline_query_handler(update, context):
    def simplify_str(s):
        return "".join(c.lower() for c in s if c.isalnum())
    def contains(needle, haystack):
        return simplify_str(haystack).find(simplify_str(needle)) != -1

    query = update.inline_query.query
    out_polls = context.user_data.get("active_polls", [])

    output_options = [ poll.get_inline_result() \
        for poll in out_polls \
        if ( len(query) == 0 or contains(query, poll.question) ) and \
        poll.ongoing \
    ]

    context.bot.answer_inline_query(update.inline_query.id, results=output_options, is_personal=True)

def callback_handler(update, context):
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
            vote.send_ballot(context.bot)
        elif req_type == CallbackDataType.SELECTING_OPTION:
            opt = decoded_data[2]
            vote.tap_option(opt)
        elif req_type == CallbackDataType.CHANGE_OF_RANK:
            vote.clear_current_ranking()
        elif req_type == CallbackDataType.SELECTING_RANK:
            rank = decoded_data[2]
            vote.tap_rank(rank)
        elif req_type == CallbackDataType.SUBMITTING_VOTE:
            vote.finalize()
        elif req_type == CallbackDataType.RETRACTING_VOTE:
            vote.retract_vote()

        vote.update_ballot()

    update.callback_query.answer()



updater = Updater(token=API_KEY)
dispatcher = updater.dispatcher

dispatcher.add_handler(get_static_handler("start"))
dispatcher.add_handler(get_static_handler("help"))

dispatcher.add_handler(CommandHandler('newpoll', new_poll_handler))
dispatcher.add_handler(CommandHandler('done', poll_done_handler))
dispatcher.add_handler(CommandHandler('mypolls', poll_list_handler))
dispatcher.add_handler(CommandHandler('cancel', cancel_handler))

dispatcher.add_handler(MessageHandler(Filters.text, message_handler))

dispatcher.add_handler(InlineQueryHandler(inline_query_handler))
dispatcher.add_handler(CallbackQueryHandler(callback_handler))

dispatcher.add_error_handler(handle_error)

# allows viewing of exceptions
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)

updater.start_webhook(listen="0.0.0.0", port=int(PORT), url_path=API_KEY,
    webhook_url='https://telegram-ranked-pairs.herokuapp.com/' + API_KEY)

updater.idle()
