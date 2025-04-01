# TNExp
A Telegram Network Explorer designed to produce an interactive web map.


## General requirements
Python 3.8.x is required. Earlier versions may work as well.

You need to have the Telegram app installed on your smartphone. Installing the desktop app on your computer is recommended.


## Requirements on Windows
Windows 10 and later versions have been confirmed to be compatible with this software.

You will need Visual Studio Tools (Community Edition), which you can download here:
[https://visualstudio.microsoft.com/thank-you-downloading-visual-studio/?sku=Community&channel=Release&version=VS2022&source=VSLandingPage&cid=2030&passive=false](https://visualstudio.microsoft.com/thank-you-downloading-visual-studio/?sku=Community&channel=Release&version=VS2022&source=VSLandingPage&cid=2030&passive=false)

During installation, you will be asked which which tools to install. You need to select "Desktop development with C++."


# Operating TNExp

## Installation
After downloading the TNExp code, install the required dependencies:
```sh
pip install -r requirements.txt
```
Next, register your application with Telegram: [https://core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id)

Follow the instructions to obtain an `api_id`. When creating a new application `Platform` should be `Web`, everything else is at your choice.

You will find a `.env.example` file. Copy and rename it to `.env`, then edit this new file and fill in the `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `TELEGRAM_PHONE_NUMBER` fields.


## Operating

When executing the Python commands below, remember that depending on your system, you may need to replace `python` commands with `py` or `python3`.

Activate the database with:
```sh
python manage.py migrate
```

Activate the interface with:
```sh
python manage.py runserver
```
Reach it on [localhost:8000](http://localhost:8000) or on [127.0.0.1:8000](http://127.0.0.1:8000)


Then, follow the link for the [admin interface](http://127.0.0.1:8000/admin/) and add a few search terms. These will be used to retrieve channels by name.

Search for channels using the defined terms:
```sh
python manage.py search_channels
```

Now, return to the [admin interface](http://127.0.0.1:8000/admin/) and assign an organization to the channels you want to investigate.

Fetch the selected channels:
```sh
python manage.py get_channels
```

You can either repeat this last step or proceed directly to drawing the graph with:
```sh
python manage.py export_network
```

When you have drawn the graph, you can see it by entering the `graph` directory and launching a web server with
```sh
python -m http.server 8001
```

Use your browser: [http://0.0.0.0:8001/telegram_graph/](http://0.0.0.0:8001/telegram_graph/)


## Options

### Telegram

| Option name | Meaning | default value |
| :---------- | :------ | ------------: |
| `TELEGRAM_API_ID` | App Id | no default value, you are required to give it a value |
| `TELEGRAM_API_HASH` | App Hash | no default value, you are required to give it a value |
| `TELEGRAM_PHONE_NUMBER` | Telephone number associated with Telegram | no default value, you are required to give it a value |
| `TELEGRAM_CRAWLER_GRACE_TIME` | time to wait between requests, in seconds | 1 |
| `TELEGRAM_CRAWLER_DOWNLOAD_IMAGES` | downloading images from messages | False |

### ForceAtlas2

| Option name | Meaning | default value |
| :---------- | :------ | ------------: |
| `FA2_ITERATIONS` | number of iterations | 20000 |

### drawing

| Option name | Meaning | default value |
| :---------- | :------ | ------------: |
| `DRAW_DEAD_LEAVES` | draw even uninteresting channels if they get inbound links (often considerably longer to draw) | False |
| `DEAD_LEAVES_COLOR` | color of dead leaves, in hex format | #596a64 |
