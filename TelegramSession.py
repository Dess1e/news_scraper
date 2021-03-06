from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, RegexHandler, ConversationHandler,
                          CallbackQueryHandler)

from DBHandler import SQLiteDB
from Exceptions import SessionException
from TelegramUser import TelegramUser

import os
from importlib import import_module as il

DEFAULT_MODULES = ':'.join([dr.split('.')[0] for dr in os.listdir('modules') if dr[-3:] == '.py'])
ALL_MODULES = {m.__name__.split('.')[1]: m for m in [il('modules.' + n[:-3]) for n in os.listdir('modules') if n != '__pycache__']}
SCRAPE_INTERVAL = 20 * 60


class TelegramSession:
    def __init__(self, tg_token):
        self.upd = Updater(tg_token)
        self.dp = self.upd.dispatcher
        self.users_db = SQLiteDB()
        self.users_cache = {}

        self.fetch_db()
        self.init_logic()

    @staticmethod
    def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
        menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
        if header_buttons:
            menu.insert(0, header_buttons)
        if footer_buttons:
            menu.append(footer_buttons)
        return menu

    def get_user(self, tg_id):
        return self.users_cache.get(tg_id)

    def add_user(self, tg_id, modules):
        if tg_id in self.users_cache:
            raise SessionException
        else:
            self.users_cache[tg_id] = TelegramUser(id=tg_id, modules=modules)

    def init_logic(self):
        dp = self.dp
        dp.add_handler(CommandHandler('start', self.cmd_start))
        dp.add_handler(CommandHandler('debug', self.cmd_debug))
        dp.add_handler(CommandHandler('stop', self.cmd_stop))
        dp.add_handler(CommandHandler('menu', self.cmd_menu))
        dp.add_handler(CommandHandler('fetch', self.cmd_fetch))
        dp.add_handler(CallbackQueryHandler(self.callback_handler))

        u = self.upd
        j = u.job_queue
        j.run_repeating(self.job_scrape, interval=10, first=1)

    def fetch_db(self):
        f = self.users_db.get_all_users()
        if not f:
            return
        else:
            for tg_id, modules in f:
                self.add_user(tg_id, modules)

    def cmd_start(self, bot, update):
        """Should be blocking because writes to db"""
        usr = update.message.from_user
        user_obj = self.get_user(usr.id)
        if user_obj:
            update.message.reply_text('You are already registered! To get help use /help')
            return
        self.users_db.add_user(tg_id=usr.id, modules=DEFAULT_MODULES)
        self.add_user(usr.id, DEFAULT_MODULES)
        update.message.reply_text('Now you are registered for updates!')

    def cmd_fetch(self, bot, update):
        usr = update.message.from_user
        user_obj = self.get_user(usr.id)
        ms = user_obj.enabled_modules
        for m in ms:
            s = m.scrape(SCRAPE_INTERVAL)
            update.message.reply_text(s)

    def cmd_debug(self, bot, update):
        usr = update.message.from_user
        update.message.reply_text('dropped to pdb session, bye')
        #pdb.set_trace()
        print(dict(ALL_MODULES))

    def cmd_menu(self, bot, update):
        usr = update.message.from_user
        reply_markup = self.build_modules_menu(usr.id)
        update.message.reply_text('Select module to switch', reply_markup=reply_markup)

    def cmd_stop(self, bot, update):
        ...

    def build_modules_menu(self, tg_id):
        btn_list = []
        enabled_modules = self.get_user(tg_id).enabled_modules
        for module in ALL_MODULES:
            suffix = ' +' if module in enabled_modules else ' -'
            btn = InlineKeyboardButton(module + suffix, callback_data=module)
            btn_list.append(btn)
        return InlineKeyboardMarkup(self.build_menu(btn_list, n_cols=2))

    def callback_handler(self, bot, update):
        cb = update.callback_query
        data = cb.data

        usr_obj = self.get_user(cb.from_user.id)
        modules = usr_obj.enabled_modules
        if data in modules:
            modules.remove(data)
            sw = 'OFF'
        else:
            modules.append(data)
            sw = 'ON'
        usr_obj.enabled_modules = modules
        self.users_db.update_user(cb.from_user.id, ':'.join(modules))
        cb.edit_message_text('Switched {} {}'.format(data, sw),
                             reply_markup=self.build_modules_menu(usr_obj.id))

    def job_scrape(self, bot, job):
        d = dict(ALL_MODULES)
        for mod_name, mod in ALL_MODULES.items():
            d[mod_name] = mod.scrape(SCRAPE_INTERVAL)

        for usr in self.users_cache.values():
            for mod in usr.enabled_modules:
                data = d.get(mod)
                if data:
                    for ar in data:
                        msg_text = '{}:* {}*\n\n{} [{}]({})\n\n{}\n'.format(mod, ar['header'], 'Read at',
                                                                            mod, ar['link'], ar['text'])
                        bot.sendPhoto(usr.id, ar['img'], caption=msg_text, parse_mode='Markdown')

    def main_loop(self):
        self.upd.start_polling()
