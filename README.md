# nyc-subway-time
## Short Description<br>
A CLI Python program showing arrival times &amp; service information for NYC Subway stations
<br>
## Requirements:
* MTA API key (https://api.mta.info/#/signup |sign up here)<br>
* ```req-lib.txt```<br>
* ```stop.txt```<br>
* ```transfers.txt```<br>
* ```stations.csv```<br>
* ```protobuf-to-dict-update.py```<br>
* ```subway_time.py```<br>
<br>
## Install modules:
```sh 
pip install -r req-lib.txt --user
```
<br>
## Long Description:
It takes a tiny bit of prep. work, but it's otherwise very easy to use (& understand):
1. Get an API key
2. Install the modules/packages/libraries
3. Replace protobuf-to-dict package with ```protobuf-to-dict-fix.py``` found in the ```requirements``` folder above;<br>(the only difference is it changes all ```long``` to ```int```);<br>the main program cannot run without the package, & the package cannot run in python 3 & above while ```long``` exists
4. Get src code (i.e. ```subway_time.py```) & static files (in ```requirements``` folder); be sure to keep in the same working dir/folder
5. Run in CLI
<br>
Has fuzzy autocomplete for station name search:
<br>
And also has an option for default settings to save your preferred station. To reset, enter ```-r``` or ```--reset``` as a CLI argument.
<br>
## CLI Arguments:
* ```-j``` ```--json```: Keep JSON train info & service alert feeds
* ```-r``` ```--reset```: Removes/resets user defaults (kept in config.json)
* ```-s``` ```--service```: Show full service alert after each timetable
<br>
Example usage:
```sh
python subway-time.py -r -s
```
