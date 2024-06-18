Configuration of devices
========================

Redvypr device configuration is realized using pydantic objects based on pydantic.BaseModel::

   import pydantic
   import typing
   class DeviceCustomConfig(pydantic.BaseModel):
       description: str = 'Calibration of sensors'



Typical configuration tasks
---------------------------
Often similar tasks for the configuration of devices are needed.
Here is an uncomplete list of typical tasks

Dynamic dictionary or list with a predefined number of allowed types to be added to the list
~~~~~~~~~~~~~
The device has a number of sensors attached. The sensors and their configuration are stored in a list.
The sensors that are allowed to be added to the list are two types, sensorA and sensorB::

    class sensorA(pydantic.BaseModel):
        sensor_id: typing.Literal['A'] = 'A'
        coeff: float = 2.0

    class sensorB(pydantic.BaseModel):
        sensor_id: typing.Literal['B'] = 'B'
        coeff: float = 1.0


The definition of a dictionary that is filled with the two sensor configurations looks like this::

   sensors: typing.Dict[str,typing.Annotated[typing.Union[sensorA,sensorB],pydantic.Field(discriminator='sensor_id')]] = pydantic.Field(default={})



Here the full example code::

    import pydantic
    import typing
    import yaml

    class sensorA(pydantic.BaseModel):
        sensor_id: typing.Literal['A'] = 'A'
        coeff: float = 2.0

    class sensorB(pydantic.BaseModel):
        sensor_id: typing.Literal['B'] = 'B'
        coeff: float = 1.0


    class DeviceCustomConfig(pydantic.BaseModel):
        description: str = 'Calibration of sensors'
        sensors: typing.Dict[str,typing.Annotated[typing.Union[sensorA,sensorB],pydantic.Field(discriminator='sensor_id')]] = pydantic.Field(default={})


    test = DeviceCustomConfig()
    A = sensorA()
    A1 = sensorA(coeff=3.0)
    B = sensorB()
    test.sensors['A'] = A
    test.sensors['A1'] = A
    test.sensors['B'] = B
    print('hints',typing.get_type_hints(test))
    # Get all options possible for attribute "sensors"
    hint1 = typing.get_type_hints(device_config)['sensors']
    #typing.Dict[str, typing.Union[__main__.sensorA, __main__.sensorB]]
    hint2 = typing.get_args(hint1)[1]
    #typing.Union[__main__.sensorA, __main__.sensorB]
    hint3 = typing.get_args(hint2)
    print('Possible options for attribute sensors are:')
    for o in hint3:
        print(o)

    # Dump the model and create a new config with the dumped data
    print('Dump')
    du = test.model_dump()
    print('du',du)
    du_yaml = yaml.dump(du)
    print('du yaml',du_yaml)
    # Reread the yaml data (maybe it was saved on the disk)
    du_reread = yaml.safe_load(du_yaml)
    # Create new config
    test_reread = device_config.model_validate(du_reread)
    print('Test reread',test_reread)


