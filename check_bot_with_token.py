import telebot


TOKEN = "6108010830:AAHaHGogxSmZKZM_bkuW2SMIX0QZp4WjljI"


bot = telebot.TeleBot(TOKEN)

bot_info = bot.get_me()

print(bot_info.username)



