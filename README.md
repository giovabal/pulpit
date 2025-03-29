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

While executing the python commands below remember that you should substitute all `python` command with `py`.


# Operating TNExp

## Installation
After downloading the TNExp code install the requirements:
```sh
pip install -r requirements.txt
```

## Operating
Activate the interface with:
```sh
python manage.py runserver
```
Reach it on [localhost:8000](http://localhost:8000) or on [127.0.0.1:8000](http://127.0.0.1:8000)

Search channels with the defined keywords:
```sh
python manage.py search_channels
```


Grab the selected channels:
```sh
python manage.py get_channels
```


Draw the graph with:
```sh
python manage.py export_network
```

