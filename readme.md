# Toast
Toast is a Discord bot for my own stuff; My instance is for servers I personally like.
You can use the code for whatever you want, though.

## Running your own instance
### Requirements
* [Python 3.8+](https://www.python.org/downloads/)
* `pip install -r requirements.txt`
* [Lavalink.jar](https://github.com/freyacodes/Lavalink/releases/latest) (for music; put into the lavalink folder)
* [Java 13.0.2](https://www.oracle.com/java/technologies/javase/jdk13-archive-downloads.html) (for Lavalink)

### Setup
* Create a `token_.py` file containing a variable named token, with your bot token
* Create [`lavalink/application.yml`](https://github.com/freyacodes/Lavalink/blob/master/LavalinkServer/application.yml.example)
* (Optional) Create a server for the bot emojis, and edit the `emoji_ids` in bot.py with your emoji IDs

### Running
* Run Lavalink with `java -jar Lavalink.jar`
* Run the bot with `python3 bot.py`
