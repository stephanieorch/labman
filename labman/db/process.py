# ----------------------------------------------------------------------------
# Copyright (c) 2017-, labman development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------

from datetime import date, datetime

import numpy as np

from . import base
from . import sql_connection
from . import user as user_module
from . import plate as plate_module
from . import container as container_module
from . import composition as composition_module
from . import equipment as equipment_module


class Process(base.LabmanObject):
    """Base process object

    Attributes
    ----------
    id
    date
    personnel
    """
    @staticmethod
    def factory(process_id):
        """Initializes the correct Process subclass

        Parameters
        ----------
        process_id : int
            The process id

        Returns
        -------
        An instance of a subclass of Process
        """
        factory_classes = {
            # 'primer template creation': TODO,
            # 'reagent creation': TODO,
            'primer working plate creation': PrimerWorkingPlateCreationProcess,
            'sample plating': SamplePlatingProcess,
            'reagent creation': ReagentCreationProcess,
            'gDNA extraction': GDNAExtractionProcess,
            '16S library prep': LibraryPrep16SProcess,
            'shotgun library prep': LibraryPrepShotgunProcess,
            'quantification': QuantificationProcess,
            'gDNA normalization': NormalizationProcess,
            'pooling': PoolingProcess,
            'sequencing': SequencingProcess}

        with sql_connection.TRN as TRN:
            sql = """SELECT description
                     FROM qiita.process_type
                        JOIN qiita.process USING (process_type_id)
                     WHERE process_id = %s"""
            TRN.add(sql, [process_id])
            p_type = TRN.execute_fetchlast()
            constructor = factory_classes[p_type]

            if constructor._table == 'qiita.process':
                instance = constructor(process_id)
            else:
                sql = """SELECT {}
                         FROM {}
                         WHERE process_id = %s""".format(
                            constructor._id_column, constructor._table)
                TRN.add(sql, [process_id])
                subclass_id = TRN.execute_fetchlast()
                instance = constructor(subclass_id)

        return instance

    @classmethod
    def _common_creation_steps(cls, user):
        with sql_connection.TRN as TRN:
            sql = """SELECT process_type_id
                     FROM qiita.process_type
                     WHERE description = %s"""
            TRN.add(sql, [cls._process_type])
            pt_id = TRN.execute_fetchlast()

            sql = """INSERT INTO qiita.process
                        (process_type_id, run_date, run_personnel_id)
                     VALUES (%s, %s, %s)
                     RETURNING process_id"""
            TRN.add(sql, [pt_id, date.today(), user.id])
            p_id = TRN.execute_fetchlast()
        return p_id

    def _get_process_attr(self, attr):
        """Returns the value of the given process attribute

        Parameters
        ----------
        attr : str
            The attribute to retrieve

        Returns
        -------
        Object
            The attribute
        """
        with sql_connection.TRN as TRN:
            sql = """SELECT {}
                     FROM qiita.process
                        JOIN {} USING (process_id)
                     WHERE {} = %s""".format(attr, self._table,
                                             self._id_column)
            TRN.add(sql, [self.id])
            return TRN.execute_fetchlast()

    @property
    def date(self):
        return self._get_process_attr('run_date')

    @property
    def personnel(self):
        return user_module.User(self._get_process_attr('run_personnel_id'))

    @property
    def process_id(self):
        return self._get_process_attr('process_id')

    @property
    def plates(self):
        """The plates being extracted by this process

        Returns
        -------
        plate : list of labman.db.Plate
            The extracted plates
        """
        with sql_connection.TRN as TRN:
            sql = """SELECT DISTINCT plate_id
                     FROM qiita.container
                        LEFT JOIN qiita.well USING (container_id)
                     WHERE latest_upstream_process_id = %s"""
            TRN.add(sql, [self.process_id])
            plate_ids = TRN.execute_fetchflatten()
        return [plate_module.Plate(plate_id) for plate_id in plate_ids]


class _Process(Process):
    """Process object

    Not all processes have a specific subtable, so we need to override the
    date and personnel attributes

    Attributes
    ----------
    id
    date
    personnel
    """
    _table = 'qiita.process'
    _id_column = 'process_id'

    @property
    def date(self):
        return self._get_attr('run_date')

    @property
    def personnel(self):
        return user_module.User(self._get_attr('run_personnel_id'))

    @property
    def process_id(self):
        return self._get_attr('process_id')


class SamplePlatingProcess(_Process):
    """Sample plating process"""

    _process_type = 'sample plating'

    @classmethod
    def create(cls, user, plate_config, plate_ext_id, volume=None):
        """Creates a new sample plating process

        Parameters
        ----------
        user : labman.db.user.User
            User performing the plating
        plate_config : labman.db.PlateConfiguration
            The sample plate configuration
        plate_ext_id : str
            The external plate id
        volume : float, optional
            Starting well volume

        Returns
        -------
        SamplePlatingProcess
        """
        with sql_connection.TRN:
            volume = volume if volume else 0
            # Add the row to the process table
            instance = cls(cls._common_creation_steps(user))

            # Create the plate
            plate = plate_module.Plate.create(plate_ext_id, plate_config)

            # By definition, all well plates are blank at the beginning
            # so populate all the wells in the plate with BLANKS
            for i in range(plate_config.num_rows):
                for j in range(plate_config.num_columns):
                    well = container_module.Well.create(
                        plate, instance, volume, i + 1, j + 1)
                    composition_module.SampleComposition.create(
                        instance, well, volume)

        return instance

    @property
    def plate(self):
        """The plate being plated by this process

        Returns
        -------
        plate : labman.db.Plate
            The plate being plated
        """
        with sql_connection.TRN as TRN:
            sql = """SELECT DISTINCT plate_id
                     FROM qiita.container
                        LEFT JOIN qiita.well USING (container_id)
                        LEFT JOIN qiita.plate USING (plate_id)
                     WHERE latest_upstream_process_id = %s"""
            TRN.add(sql, [self.id])
            plate_id = TRN.execute_fetchlast()
        return plate_module.Plate(plate_id)

    def update_well(self, row, col, content):
        """Updates the content of a well

        Parameters
        ----------
        row: int
            The well row
        col: int
            The well column
        content: str
            The new contents of the well
        """
        self.plate.get_well(row, col).composition.update(content)


class ReagentCreationProcess(_Process):
    """Reagent creation process"""

    _process_type = 'reagent creation'

    @classmethod
    def create(cls, user, external_id, volume, reagent_type):
        """Creates a new reagent creation process

        Parameters
        ----------
        user : labman.db.user.User
            User adding the reagent to the system
        external_id: str
            The external id of the reagent
        volume: float
            Initial reagent volume
        reagent_type : str
            The type of the reagent

        Returns
        -------
        ReagentCreationProce
        """
        with sql_connection.TRN:
            # Add the row to the process table
            instance = cls(cls._common_creation_steps(user))

            # Create the tube and the composition
            tube = container_module.Tube.create(instance, external_id, volume)
            composition_module.ReagentComposition.create(
                instance, tube, volume, reagent_type, external_id)

        return instance

    @property
    def tube(self):
        """The tube storing the reagent"""
        with sql_connection.TRN as TRN:
            sql = """SELECT tube_id
                     FROM qiita.tube
                        LEFT JOIN qiita.container USING (container_id)
                     WHERE latest_upstream_process_id = %s"""
            TRN.add(sql, [self.process_id])
            tube_id = TRN.execute_fetchlast()
        return container_module.Tube(tube_id)


class PrimerWorkingPlateCreationProcess(Process):
    """Primer working plate creation process object

    Attributes
    ----------
    primer_set
    master_set_order_number
    """
    _table = 'qiita.primer_working_plate_creation_process'
    _id_column = 'primer_working_plate_creation_process_id'
    _process_type = 'primer working plate creation'

    @property
    def primer_set(self):
        """The primer set template from which the working plates are created

        Returns
        -------
        PrimerSet
        """
        return composition_module.PrimerSet(self._get_attr('primer_set_id'))

    @property
    def master_set_order(self):
        """The master set order

        Returns
        -------
        str
        """
        return self._get_attr('master_set_order_number')


class GDNAExtractionProcess(Process):
    """gDNA extraction process object

    Attributes
    ----------
    robot
    kit
    tool

    See Also
    --------
    Process
    """
    _table = 'qiita.gdna_extraction_process'
    _id_column = 'gdna_extraction_process_id'
    _process_type = 'gDNA extraction'

    @property
    def robot(self):
        """The robot used during extraction

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(
            self._get_attr('extraction_robot_id'))

    @property
    def kit(self):
        """The kit used during extraction

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('extraction_kit_id'))

    @property
    def tool(self):
        """The tool used during extraction

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(self._get_attr('extraction_tool_id'))

    @classmethod
    def create(cls, user, robot, tool, kit, plates, volume):
        """Creates a new gDNA extraction process

        Parameters
        ----------
        user : labman.db.user.User
            User performing the gDNA extraction
        robot: labman.db.equipment.Equipment
            The robot used for the extraction
        tool: labman.db.equipment.Equipment
            The tool used for the extraction
        kit : labman.db.composition.ReagentComposition
            The extraction kit used for the extraction
        plates: list of labman.db.plate.Plate
            The plates to be extracted
        volume : float
            The volume extracted

        Returns
        -------
        GDNAExtractionProcess
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            # Add the row to the gdna_extraction_process table
            sql = """INSERT INTO qiita.gdna_extraction_process
                        (process_id, extraction_robot_id, extraction_kit_id,
                         extraction_tool_id)
                     VALUES (%s, %s, %s, %s)
                     RETURNING gdna_extraction_process_id"""
            TRN.add(sql, [process_id, robot.id, kit.id, tool.id])
            instance = cls(TRN.execute_fetchlast())

            for plate in plates:
                # Create the extracted plate
                plate_ext_id = 'gdna - %s' % plate.external_id

                plate_config = plate.plate_configuration
                gdna_plate = plate_module.Plate.create(plate_ext_id,
                                                       plate_config)
                plate_layout = plate.layout

                # Add the wells to the new plate
                for i in range(plate_config.num_rows):
                    for j in range(plate_config.num_columns):
                        well = container_module.Well.create(
                            gdna_plate, instance, volume, i + 1, j + 1)
                        composition_module.GDNAComposition.create(
                            instance, well, volume,
                            plate_layout[i][j].composition)

        return instance


class LibraryPrep16SProcess(Process):
    """16S Library Prep process object

    Attributes
    ----------
    master_mix
    tm300_8_tool
    tm50_8_tool
    water_lot
    processing_robot

    See Also
    --------
    Process
    """
    _table = 'qiita.library_prep_16s_process'
    _id_column = 'library_prep_16s_process_id'
    _process_type = '16S library prep'

    @classmethod
    def create(cls, user, master_mix, water, robot, tm300_8_tool, tm50_8_tool,
               volume, plates):
        """Creates a new 16S library prep process

        Parameters
        ----------
        user : labman.db.user.User
            User performing the library prep
        master_mix : labman.db.composition.ReagentComposition
            The master mix used for preparing the library
        water : labman.db.composition.ReagentComposition
            The water used for preparing the library
        robot : labman.db.equipment.equipment
            The robot user for preparing the library
        tm300_8_tool : labman.db.equipment.equipment
            The tm300_8_tool user for preparing the library
        tm50_8_tool : labman.db.equipment.equipment
            The tm50_8_tool user for preparing the library
        volume : float
            The initial volume in the wells
        plates : list of tuples of (Plate, Plate)
            The firt plate of the tuple is the gDNA plate in which a new
            prepis going to take place and the second plate is the primer
            plate used.

        Returns
        -------
        LibraryPrep16SProcess
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            # Add the row to the library_prep_16s_process
            sql = """INSERT INTO qiita.library_prep_16s_process
                        (process_id, master_mix_id, tm300_8_tool_id,
                         tm50_8_tool_id, water_id, processing_robot_id)
                     VALUES (%s, %s, %s, %s, %s, %s)
                     RETURNING library_prep_16s_process_id"""
            TRN.add(sql, [process_id, master_mix.id, tm300_8_tool.id,
                          tm50_8_tool.id, water.id, robot.id])
            instance = cls(TRN.execute_fetchlast())

            for gdna_plate, primer_plate in plates:
                # Create the library plate
                plate_ext_id = '16S library - %s' % gdna_plate.external_id

                plate_config = gdna_plate.plate_configuration
                library_plate = plate_module.Plate.create(plate_ext_id,
                                                          plate_config)
                gdna_layout = gdna_plate.layout
                primer_layout = primer_plate.layout
                for i in range(plate_config.num_rows):
                    for j in range(plate_config.num_columns):
                        well = container_module.Well.create(
                            library_plate, instance, volume, i + 1, j + 1)
                        composition_module.LibraryPrep16SComposition.create(
                            instance, well, volume,
                            gdna_layout[i][j].composition,
                            primer_layout[i][j].composition)

        return instance

    @property
    def master_mix(self):
        """The master mix used

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('master_mix_id'))

    @property
    def tm300_8_tool(self):
        """The tm300_8 tool used

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(
            self._get_attr('tm300_8_tool_id'))

    @property
    def tm50_8_tool(self):
        """The tm50_8 tool used

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(self._get_attr('tm50_8_tool_id'))

    @property
    def water_lot(self):
        """The water lot used

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('water_id'))

    @property
    def processing_robot(self):
        """The processing robot used

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(
            self._get_attr('processing_robot_id'))


class NormalizationProcess(Process):
    """Normalization process object

    Attributes
    ----------
    quantification_process
    water_lot

    See Also
    --------
    Process
    """
    _table = 'qiita.normalization_process'
    _id_column = 'normalization_process_id'
    _process_type = 'gDNA normalization'

    @property
    def quantification_process(self):
        """The quantification process used

        Returns
        -------
        QuantificationProcess
        """
        return QuantificationProcess(
            self._get_attr('quantification_process_id'))

    @property
    def water_lot(self):
        """The water lot used

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('water_lot_id'))


class LibraryPrepShotgunProcess(Process):
    """Shotgun Library Prep process object

    Attributes
    ----------
    kappa_hyper_plus_kit
    stub_lot
    normalization_process

    See Also
    --------
    Process
    """
    _table = 'qiita.library_prep_shotgun_process'
    _id_column = 'library_prep_shotgun_process_id'
    _process_type = 'shotgun library prep'

    @property
    def kappa_hyper_plus_kit(self):
        """The Kappa Hyper plus kit used

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('kappa_hyper_plus_kit_id'))

    @property
    def stub_lot(self):
        """The stub lot used

        Returns
        -------
        ReagentComposition
        """
        return composition_module.ReagentComposition(
            self._get_attr('stub_lot_id'))

    @property
    def normalization_process(self):
        """The normalization process used

        Returns
        -------
        NormalizationProcess
        """
        return NormalizationProcess(self._get_attr('normalization_process_id'))


class QuantificationProcess(Process):
    """Quantification process object

    Attributes
    ----------
    concentrations

    See Also
    --------
    Process
    """
    _table = 'qiita.quantification_process'
    _id_column = 'quantification_process_id'
    _process_type = 'quantification'

    @staticmethod
    def parse(contents):
        """Parses the output of a plate reader

        The format supported here is a tab delimited file in which the first
        line contains the fitting curve followed by (n) blank lines and then a
        tab delimited matrix with the values

        Parameters
        ----------
        contents : str
            The contents of the plate reader output

        Returns
        -------
        np.array of floats
            A 2D array of floats
        """
        data = []
        for line in contents.splitlines():
            line = line.strip()
            if not line or line.startswith('Curve'):
                continue
            data.append(line.split())

        return np.asarray(data, dtype=np.float)

    @classmethod
    def create_manual(cls, user, quantifications):
        """Creates a new manual quantification process

        Parameters
        ----------
        user: labman.db.user.User
            User performing the quantification process
        quantifications: list of dict
            The quantifications in the form of {'composition': Composition,
            'conenctration': float}

        Returns
        -------
        QuantificationProcess
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            # Add the row to the quantification process table
            sql = """INSERT INTO qiita.quantification_process (process_id)
                     VALUES (%s) RETURNING quantification_process_id"""
            TRN.add(sql, [process_id])
            instance = cls(TRN.execute_fetchlast())

            sql = """INSERT INTO qiita.concentration_calculation
                        (quantitated_composition_id, upstream_process_id,
                         raw_concentration)
                     VALUES (%s, %s, %s)"""
            sql_args = []
            for quant in quantifications:
                sql_args.append([quant['composition'].composition_id,
                                 instance.id, quant['concentration']])

            TRN.add(sql, sql_args, many=True)
            TRN.execute()
        return instance

    @classmethod
    def create(cls, user, plate, concentrations):
        """Creates a new quantification process

        Parameters
        ----------
        user: labman.db.user.User
            User performing the quantification process
        plate: labman.db.plate.Plate
            The plate being quantified
        concentrations: 2D np.array
            The plate concentrations

        Returns
        -------
        QuantificationProcess
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            # Add the row to the quantification process table
            sql = """INSERT INTO qiita.quantification_process (process_id)
                     VALUES (%s) RETURNING quantification_process_id"""
            TRN.add(sql, [process_id])
            instance = cls(TRN.execute_fetchlast())

            sql = """INSERT INTO qiita.concentration_calculation
                        (quantitated_composition_id, upstream_process_id,
                         raw_concentration)
                     VALUES (%s, %s, %s)"""
            sql_args = []
            layout = plate.layout
            for p_row, c_row in zip(layout, concentrations):
                for well, conc in zip(p_row, c_row):
                    sql_args.append([well.composition.composition_id,
                                     instance.id, conc])

            TRN.add(sql, sql_args, many=True)
            TRN.execute()

            return instance

    @property
    def concentrations(self):
        """The concentrations measured

        Returns
        -------
        list of (Composition, float)
        """
        with sql_connection.TRN as TRN:
            sql = """SELECT quantitated_composition_id, raw_concentration
                     FROM qiita.concentration_calculation
                     WHERE upstream_process_id = %s
                     ORDER BY concentration_calculation_id"""
            TRN.add(sql, [self._id])
            return [(composition_module.Composition.factory(comp_id), raw_con)
                    for comp_id, raw_con in TRN.execute_fetchindex()]


class PoolingProcess(Process):
    """Pooling process object

    Attributes
    ----------
    quantification_process
    robot

    See Also
    --------
    Process
    """
    _table = 'qiita.pooling_process'
    _id_column = 'pooling_process_id'
    _process_type = 'pooling'

    @classmethod
    def create(cls, user, quantification_process, pool_name, volume,
               input_compositions, robot=None):
        """Creates a new pooling process

        Parameters
        ----------
        user: labman.db.user.User
            User performing the pooling process
        quantification_process: labman.db.process.QuantificationProcess
            The quantification process this pooling is based on
        pool_name: str
            The name of the new pool
        volume: float
            The initial volume
        input_compositions: list of dicts
            The input compositions for the pool {'composition': Composition,
            'input_volume': float, 'percentage_of_output': float}
        robot: labman.equipment.Equipment, optional
            The robot performing the pooling, if not manual

        Returns
        -------
        PoolingProcess
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            # Add the row to the pooling process table
            sql = """INSERT INTO qiita.pooling_process
                        (process_id, quantification_process_id, robot_id)
                     VALUES (%s, %s, %s)
                     RETURNING pooling_process_id"""
            r_id = robot.id if robot is not None else None
            TRN.add(sql, [process_id, quantification_process.id, r_id])
            instance = cls(TRN.execute_fetchlast())

            # Create the new pool
            tube = container_module.Tube.create(instance, pool_name, volume)
            pool = composition_module.PoolComposition.create(
                instance, tube, volume)

            # Link the pool with its contents
            sql = """INSERT INTO qiita.pool_composition_components
                        (output_pool_composition_id, input_composition_id,
                         input_volume, percentage_of_output)
                     VALUES (%s, %s, %s, %s)"""
            sql_args = []
            for in_comp in input_compositions:
                sql_args.append([pool.id,
                                 in_comp['composition'].composition_id,
                                 in_comp['input_volume'],
                                 in_comp['percentage_of_output']])
            TRN.add(sql, sql_args, many=True)
            TRN.execute()

        return instance

    @property
    def quantification_process(self):
        """The quantification process used

        Returns
        -------
        QuantificationProcess
        """
        return QuantificationProcess(
            self._get_attr('quantification_process_id'))

    @property
    def robot(self):
        """The robot used

        Returns
        -------
        Equipment
        """
        return equipment_module.Equipment(self._get_attr('robot_id'))


class SequencingProcess(Process):
    """Sequencing process object

    Attributes
    ----------

    See Also
    --------
    Process
    """
    _table = 'qiita.sequencing_process'
    _id_column = 'sequencing_process_id'
    _process_type = 'sequencing'

    @classmethod
    def create(cls, user, pool, run_name, sequencer, fwd_cycles, rev_cycles,
               assay, principal_investigator, contact_0, contact_1=None,
               contact_2=None):
        """Creates a new sequencing process

        Parameters
        ----------
        user : labman.db.user.User
            User preparing the sequencing
        pool: labman.db.composition.PoolComposition
            The pool being sequenced
        run_name: str
            The run name
        sequencer: labman.db.equipment.Equipment
            The sequencer used
        fwd_cycles : int
            The number of forward cycles
        rev_cycles : int
            The number of reverse cycles
        assay : str
            The assay instrument (e.g., Kapa Hyper Plus)
        principal_investigator : labman.db.user.User
            The principal investigator to list in the run
        contact_0 : labman.db.user.User
            Additional contact person
        contact_1 : labman.db.user.User, optional
            Additional contact person
        contact_2 : labman.db.user.User, optional
            Additional contact person

        Returns
        -------
        SequencingProcess

        Raises
        ------
        ValueError
            If the number of cycles are <= 0
        """
        with sql_connection.TRN as TRN:
            # Add the row to the process table
            process_id = cls._common_creation_steps(user)

            if fwd_cycles <= 0 or not isinstance(fwd_cycles, int):
                raise ValueError("fwd_cycles must be > 0")
            if rev_cycles <= 0 or not isinstance(rev_cycles, int):
                raise ValueError("rev_cycles must be > 0")

            # Add the row to the sequencing table
            sql = """INSERT INTO qiita.sequencing_process
                        (process_id, pool_composition_id, sequencer_id,
                         fwd_cycles, rev_cycles, assay, principal_investigator,
                         contact_0, contact_1, contact_2, run_name)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                     RETURNING sequencing_process_id"""
            c1_id = contact_1.id if contact_1 is not None else None
            c2_id = contact_2.id if contact_2 is not None else None
            TRN.add(sql, [process_id, pool.id, sequencer.id, fwd_cycles,
                          rev_cycles, assay, principal_investigator.id,
                          contact_0.id, c1_id, c2_id, run_name])
            instance = cls(TRN.execute_fetchlast())
        return instance

    @property
    def run_name(self):
        return self._get_attr('run_name')

    @property
    def pool(self):
        return composition_module.PoolComposition(
            self._get_attr('pool_composition_id'))

    @property
    def sequencer(self):
        return equipment_module.Equipment(self._get_attr('sequencer_id'))

    @property
    def fwd_cycles(self):
        return self._get_attr('fwd_cycles')

    @property
    def rev_cycles(self):
        return self._get_attr('rev_cycles')

    @property
    def assay(self):
        return self._get_attr('assay')

    @property
    def principal_investigator(self):
        return user_module.User(self._get_attr('principal_investigator'))

    @property
    def contact_0(self):
        return user_module.User(self._get_attr('contact_0'))

    @property
    def contact_1(self):
        return user_module.User(self._get_attr('contact_1'))

    @property
    def contact_2(self):
        return user_module.User(self._get_attr('contact_2'))

    def format_sample_sheet(self, run_type='Target Gene'):
        """Writes a sample sheet

        Parameters
        ----------
        run_type : {"Target Gene", "Shotgun"}
            Which data sheet structure to use

        Sample Sheet Note
        -----------------
        If the instrument type is a MiSeq, any lane information per-sample will
        be disregarded. If instrument type is a HiSeq, each sample must include
        a "lane" key.
        If the run type is Target Gene, then sample details are disregarded
        with the exception of determining the lanes.
        IF the run type is shotgun, then the following keys are required:
            - sample-id
            - i7-index-id
            - i7-index
            - i5-index-id
            - i5-index

        Raises
        ------
        ValueError
            If an unknown run type is specified

        Return
        ------
        str
            The formatted sheet.
        """
        run_type = 'Target Gene'
        if run_type == 'Target Gene':
            sample_header = DATA_TARGET_GENE_STRUCTURE
            sample_detail = DATA_TARGET_GENE_SAMPLE_STRUCTURE
        elif run_type == 'Shotgun':
            sample_header = DATA_SHOTGUN_STRUCTURE
            sample_detail = DATA_SHOTGUN_SAMPLE_STRUCTURE
        else:
            raise ValueError("%s is not a known run type" %
                             run_type)

        # if its a miseq, there isn't lane information
        instrument_type = self.sequencer.equipment_type
        if instrument_type == 'miseq':
            header_prefix = ''
            header_suffix = ','
            sample_prefix = ''
            sample_suffix = ','
        elif instrument_type == 'hiseq':
            header_prefix = 'Lane,'
            header_suffix = ''
            sample_prefix = '%(lane)d,'
            sample_suffix = ''

        sample_header = header_prefix + sample_header + header_suffix
        sample_detail_fmt = sample_prefix + sample_detail + sample_suffix

        if run_type == 'Target Gene':
            if instrument_type == 'hiseq':
                pass
                # TODO: how to gather the lane information? is it a lane per
                # pool?
                # lanes = sorted({samp['lane'] for samp in sample_information})
                # sample_details = []
                # for idx, lane in enumerate(lanes):
                #     # make a unique run-name on the assumption
                #     this is required
                #     detail = {'lane': lane, 'run_name': run_name + str(idx)}
                #     sample_details.append(sample_detail_fmt % detail)
            else:
                sample_details = [sample_detail_fmt % {
                    'run_name': self.run_name}]
        else:
            pass
            # TODO: gather the information for shotgun
            # sample_details = [sample_detail_fmt % samp
            #                   for samp in sample_information]

        base_sheet = self._format_general()

        full_sheet = "%s%s\n%s\n" % (base_sheet, sample_header,
                                     '\n'.join(sample_details))

        return full_sheet

    def _format_general(self):
        """Format the initial parts of a sample sheet

        Returns
        -------
        str
            The populated non-sample parts of the sample sheet.
        """
        pi = self.principal_investigator
        c0 = self.contact_0
        fmt = {'run_name': self.run_name,
               'assay': self.assay,
               'date': datetime.now().strftime("%m/%d/%Y"),
               'fwd_cycles': self.fwd_cycles,
               'rev_cycles': self.rev_cycles,
               'labman_id': self.id,
               'pi_name': pi.name,
               'pi_email': pi.email,
               'contact_0_name': c0.name,
               'contact_0_email': c0.email}

        c1 = self.contact_1
        c2 = self.contact_2
        optional = {
            'contact_1_name': c1.name if c1 is not None else None,
            'contact_1_email': c1.email if c1 is not None else None,
            'contact_2_name': c2.name if c2 is not None else None,
            'contact_2_email': c2.email if c2 is not None else None}

        for k, v in fmt.items():
            if v is None or v == '':
                raise ValueError("%s is required")
        fmt.update(optional)

        return SHEET_STRUCTURE % fmt


SHEET_STRUCTURE = """[Header],,,,,,,,,,
IEMFileVersion,4,,,,,,,,,
Investigator Name,%(pi_name)s,,,,PI,%(pi_name)s,%(pi_email)s,,,
Experiment Name,%(run_name)s,,,,Contact,%(contact_0_name)s,%(contact_1_name)s,%(contact_2_name)s,,
Date,%(date)s,,,,,%(contact_0_email)s,%(contact_1_email)s,%(contact_2_email)s,,
Workflow,GenerateFASTQ,,,,,,,,,
Application,FASTQ Only,,,,,,,,,
Assay,%(assay)s,,,,,,,,,
Description,labman ID,%(labman_id)d,,,,,,,,
Chemistry,Default,,,,,,,,,
,,,,,,,,,,
[Reads],,,,,,,,,,
%(fwd_cycles)d,,,,,,,,,,
%(rev_cycles)d,,,,,,,,,,
,,,,,,,,,,
[Settings],,,,,,,,,,
ReverseComplement,0,,,,,,,,,
,,,,,,,,,,
[Data],,,,,,,,,,
"""  # noqa: E501

DATA_TARGET_GENE_STRUCTURE = "Sample_ID,Sample_Name,Sample_Plate,Sample_Well,I7_Index_ID,index,Sample_Project,Description,,"  # noqa: E501

DATA_TARGET_GENE_SAMPLE_STRUCTURE = "%(run_name)s,,,,,NNNNNNNNNNNN,,,,,"

DATA_SHOTGUN_STRUCTURE = "Sample_ID,Sample_Name,Sample_Plate,Sample_Well,I7_Index_ID,index,I5_Index_ID,index2,Sample_Project,Description"  # noqa: E501

DATA_SHOTGUN_SAMPLE_STRUCTURE = "%(sample_id)s,,,,%(i7_index_id)s,%(i7_index)s,%(i5_index_id)s,%(i5_index)s,,"  # noqa: E501