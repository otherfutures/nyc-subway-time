# nyc-subway-time

## Short Description<br>

A CLI Python program showing arrival timetables, service information, & ADA access for NYC Subway stations.<br>

<img src="readme/sample.jpg" alt="screenshot" width="400">

## Requirements

* MTA API key<br>
* ```req-lib.txt```<br>
* ```stop.txt```<br>
* ```transfers.txt```<br>
* ```stations.csv```<br>
* ```protobuf-to-dict-update.py```(might be optional, see below)<br>
* ```subway_time.py```<br>
* python 3.x or above<br><br>

## Install modules from req-lib.txt

```sh
pip install -r requirements.txt --user
```

## Long Description

It takes a tiny bit of prep. work, but it's otherwise very easy to use (& understand):<br>

1. [Get an API key](https://api.mta.info/#/signup)<br>
2. [Install the modules/packages/libraries](https://github.com/otherfutures/nyc-subway-time/edit/main/README.md#install-modules)<br>
3. (**OPTIONAL, depending on whether the library is giving you trouble**)<br>
Replace protobuf3-to-dict package code with that of ```protobuf-to-dict-fix.py``` (found in the [requirements](https://github.com/otherfutures/nyc-subway-time/tree/main/requirements) folder above). The only difference between the two is the latter changes all ```long``` to ```int```; ```nyc-subway-time.py``` cannot run without the package, & the package cannot run in python 3 and above while ```long``` exists<br><br>If you're having trouble finding where your packages are, try running

```python
pip show protobuf3-to-dict
```

or alternatively, try running the following in a Python file to get the folder pathname:

```python
import site
print(site.getsitepackages())
```

4. Get source code (i.e. ```subway_time.py```) and static files (found in [requirements](https://github.com/otherfutures/nyc-subway-time/tree/main/requirements) folder); be sure to keep everything in the same working dir/folder<br>
5. Add API key to src code (i.e. line 17: API_KEY)
6. Run<br><br>

Has fuzzy autocomplete for station name search:<br><br>
<img src="readme/fuzzysearch01.jpg" alt="union sq search" width="350"><br>
<img src="readme/fuzzysearch02.jpg" alt="union sq search" width="350"><br>

And also has an option for default settings to save your preferred station. To reset, enter ```-r``` or ```--reset``` as a CLI argument.<br>

Will tell you of upcoming service announcements as well as current ones:<br><br>
<img src="readme/service01.jpg" alt="servicealerts" width="350"><br>

It's written to be (reasonably) robust when used in good faith :muscle:

## CLI Arguments

* ```-j``` ```--json```: Keep JSON train info and service alert feeds<br>
* ```-r``` ```--reset```: Removes/resets user defaults (kept in ```config.json```)<br>
* ```-s``` ```--service```: Show full service alert after each timetable<br><br>

### Example usage:<br>

```sh
python subway-time.py -r -s
```

## (Possible) Future Updates

* LIRR and/or MetroNorth
* MTA buses
* NJ PATH

## See Also

Other Python realtime subway lookups; very helpful to me while researching & building this project! :D

* [underground](https://github.com/nolanbconaway/underground)
* [nyct-gtfs](https://github.com/Andrew-Dickinson/nyct-gtfs)
