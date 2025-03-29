# TNExp
A Telegram Network Explorer aimed to produce an interactive web map


## General requirements
Python 3.8.x is required. Earlier versions could work too.

You need Telegram app installed on your smartphone, having the desktop app installed on your computer is recommended.


## Requirements on Windows
Windows 10 and later versions have been confirmed to be compatible with this software.

You will need Visual Studio Tools (Community Edition), which you can download here:
[https://visualstudio.microsoft.com/thank-you-downloading-visual-studio/?sku=Community&channel=Release&version=VS2022&source=VSLandingPage&cid=2030&passive=false](https://visualstudio.microsoft.com/thank-you-downloading-visual-studio/?sku=Community&channel=Release&version=VS2022&source=VSLandingPage&cid=2030&passive=false)

During installation, you will be asked which tools to install. You need to select "Desktop development with C++."


# Operating TNExp

## Installation
After downloading the TNExp code install the requirements:
```sh
pip install -r requirements.txt
```

Then you need to register your application to Telegram: [https://core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id)
Follow the instructions to get an `api_id`.

You will find a `env.example` file, copy and rename it to `.env`. Edit this new file and fill the `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` and `TELEGRAM_PHONE_NUMBER`.


## Operating

When executing the python commands below remember that, depending on your system, you could have to substitute all `python` commands with `py` or `python3`.

Activate the interface with:
```sh
python manage.py runserver
```
Reach it on [localhost:8000](http://localhost:8000) or on [127.0.0.1:8000](http://127.0.0.1:8000)


Then follow the link for the [admin interface](http://127.0.0.1:8000/admin/) and add a few search terms, they will be used for retrieving channels by their names.
Search channels with the defined terms:
```sh
python manage.py search_channels
```

Now go back to the [admin interface](http://127.0.0.1:8000/admin/) and give an organization the the ones you want to investigate.

Grab the selected channels:
```sh
python manage.py get_channels
```

Now you can iterate this last step or you can directly draw the graph with:
```sh
python manage.py export_network
```

