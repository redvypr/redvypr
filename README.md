redvypr: Realtimedata viewer and processor (in python)
======================================================

Overview
--------
redvypr offers a python based framework to connect sensors and devices providing digital data and the possibilities to merge/process/save the data. See figure below for an artistic overview of the general structure of redvypr:

![Artistic view of redvyprs general structure](doc/source/figures/redvypr_overview_merged_v01_small.png)

Introduction
------------

Sampling data from sensors does always require similar tasks:

- storing the data
- adding metadata like position, time, experiment (logbook)
- inspecting the data to determine faulty data
- visualizing data for first interpretations

Sensors are more and more equipped with a direct digital output, that
makes it possible to fulfill the above defined tasks directly on a
computer.

redvypr aims to unifiy these tasks by creating a framework that allows
to store, visualize and transfer data from various sensors. As sensors
are arbitrarily complex in handling and reading, it is left to the user
to implement custom sensors into redvypr using the common interfaces
provided.

Documentation
-------------
Find [here](https://redvypr.readthedocs.io) the documentation of redvypr.


