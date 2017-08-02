#!/usr/bin/env python

# =============================================================================
# MODULE DOCSTRING
# =============================================================================

"""
Custom OpenMM Forces classes and utilities.

"""


# =============================================================================
# GLOBAL IMPORTS
# =============================================================================

from simtk import openmm, unit

from openmmtools.constants import ONE_4PI_EPS0


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def find_nonbonded_force(system):
    """Find the first OpenMM `NonbondedForce` in the system.

    Parameters
    ----------
    system : simtk.openmm.System
        The system to search.

    Returns
    -------
    nonbonded_force : simtk.openmm.NonbondedForce
        The first `NonbondedForce` object in `system`.

    Raises
    ------
    ValueError
        If the system contains multiple `NonbondedForce`s

    """
    nonbonded_force = None
    for force in system.getForces():
        if isinstance(force, openmm.NonbondedForce):
            if nonbonded_force is not None:
                raise ValueError('The System has multiple NonbondedForces')
            nonbonded_force = force
    return nonbonded_force


def iterate_nonbonded_forces(system):
    """Iterate over all OpenMM `NonbondedForce`s in `system`.

    Parameters
    ----------
    system : simtk.openmm.System
        The system to search.

    Yields
    ------
    force : simtk.openmm.NonbondedForce
        A `NonbondedForce` object in `system`.

    """
    for force in system.getForces():
        if isinstance(force, openmm.NonbondedForce):
            yield force


# =============================================================================
# REACTION FIELD
# =============================================================================

class UnshiftedReactionFieldForce(openmm.CustomNonbondedForce):
    """A force modelling switched reaction-field electrostatics.

    Contrarily to a normal `NonbondedForce` with `CutoffPeriodic` nonbonded
    method, this force sets the `c_rf` to 0.0 and uses a switching function
    to avoid forces discontinuities at the cutoff distance.

    Parameters
    ----------
    cutoff_distance : simtk.unit.Quantity, default 15*angstroms
        The cutoff distance (units of distance).
    switch_width : simtk.unit.Quantity, default 1.0*angstrom
        Switch width for electrostatics (units of distance).
    reaction_field_dielectric : float
        The dielectric constant used for the solvent.

    """

    def __init__(self, cutoff_distance=15*unit.angstroms, switch_width=1.0*unit.angstrom,
                 reaction_field_dielectric=78.3):
        k_rf = cutoff_distance**(-3) * (reaction_field_dielectric - 1.0) / (2.0*reaction_field_dielectric + 1.0)

        # Energy expression omits c_rf constant term.
        energy_expression = "ONE_4PI_EPS0*chargeprod*(r^(-1) + k_rf*r^2);"
        energy_expression += "chargeprod = charge1*charge2;"
        energy_expression += "k_rf = {:f};".format(k_rf.value_in_unit_system(unit.md_unit_system))
        energy_expression += "ONE_4PI_EPS0 = {:f};".format(ONE_4PI_EPS0)  # already in OpenMM units

        # Create CustomNonbondedForce.
        super(UnshiftedReactionFieldForce, self).__init__(energy_expression)

        # Add parameters.
        self.addPerParticleParameter("charge")

        # Configure force.
        self.setNonbondedMethod(openmm.CustomNonbondedForce.CutoffPeriodic)
        self.setCutoffDistance(cutoff_distance)
        self.setUseLongRangeCorrection(False)
        if switch_width is not None:
            self.setUseSwitchingFunction(True)
            self.setSwitchingDistance(cutoff_distance - switch_width)
        else:  # Truncated
            self.setUseSwitchingFunction(False)

    @classmethod
    def from_nonbonded_force(cls, nonbonded_force, switch_width=1.0*unit.angstrom):
        """Copy constructor from an OpenMM `NonbondedForce`.

        The returned force has same cutoff distance and dielectric, and
        its particles have the same charges. Exclusions corresponding to
        `nonbonded_force` exceptions are also added.

        .. warning
            This only creates the force object. The electrostatics in
            `nonbonded_force` remains unmodified. Use the function
            `replace_reaction_field` to correctly convert a system to
            use an unshifted reaction field potential.

        Parameters
        ----------
        nonbonded_force : simtk.openmm.NonbondedForce
            The nonbonded force to copy.
        switch_width : simtk.unit.Quantity
            Switch width for electrostatics (units of distance).

        Returns
        -------
        reaction_field_force : UnshiftedReactionFieldForce
            The reaction field force with copied particles.

        """
        # OpenMM gives unitless values.
        cutoff_distance = nonbonded_force.getCutoffDistance()
        reaction_field_dielectric = nonbonded_force.getReactionFieldDielectric()
        reaction_field_force = cls(cutoff_distance, switch_width, reaction_field_dielectric)

        # Set particle charges.
        for particle_index in range(nonbonded_force.getNumParticles()):
            charge, sigma, epsilon = nonbonded_force.getParticleParameters(particle_index)
            reaction_field_force.addParticle([charge])

        # Add exclusions to CustomNonbondedForce.
        for exception_index in range(nonbonded_force.getNumExceptions()):
            iatom, jatom, chargeprod, sigma, epsilon = nonbonded_force.getExceptionParameters(exception_index)
            reaction_field_force.addExclusion(iatom, jatom)

        return reaction_field_force

    @classmethod
    def from_system(cls, system, switch_width=1.0*unit.angstrom):
        """Copy constructor from the first OpenMM `NonbondedForce` in `system`.

        If multiple `NonbondedForce`s are found, an exception is raised.

        .. warning
            This only creates the force object. The electrostatics in
            `nonbonded_force` remains unmodified. Use the function
            `replace_reaction_field` to correctly convert a system to
            use an unshifted reaction field potential.

        Parameters
        ----------
        system : simtk.openmm.System
            The system containing the nonbonded force to copy.
        switch_width : simtk.unit.Quantity
            Switch width for electrostatics (units of distance).

        Returns
        -------
        reaction_field_force : UnshiftedReactionFieldForce
            The reaction field force.

        Raises
        ------
        ValueError
            If multiple `NonbondedForce`s are found in the system.

        See Also
        --------
        UnshiftedReactionField.from_nonbonded_force

        """
        nonbonded_force = find_nonbonded_force(system)
        return cls.from_nonbonded_force(nonbonded_force, switch_width)

class SwitchedReactionFieldForce(openmm.CustomNonbondedForce):
    """A force modelling switched reaction-field electrostatics.

    Parameters
    ----------
    cutoff_distance : simtk.unit.Quantity, default 15*angstroms
        The cutoff distance (units of distance).
    switch_width : simtk.unit.Quantity, default 1.0*angstrom
        Switch width for electrostatics (units of distance).
    reaction_field_dielectric : float
        The dielectric constant used for the solvent.

    """

    def __init__(self, cutoff_distance=15*unit.angstroms, switch_width=1.0*unit.angstrom,
                 reaction_field_dielectric=78.3):
        k_rf = cutoff_distance**(-3) * (reaction_field_dielectric - 1.0) / (2.0*reaction_field_dielectric + 1.0)
        c_rf = cutoff_distance**(-1) * (3*reaction_field_dielectric) / (2.0*reaction_field_dielectric + 1.0)

        # Energy expression omits c_rf constant term.
        energy_expression = "ONE_4PI_EPS0*chargeprod*(r^(-1) + k_rf*r^2 - c_rf);"
        energy_expression += "chargeprod = charge1*charge2;"
        energy_expression += "k_rf = {:f};".format(k_rf.value_in_unit_system(unit.md_unit_system))
        energy_expression += "c_rf = {:f};".format(c_rf.value_in_unit_system(unit.md_unit_system))
        energy_expression += "ONE_4PI_EPS0 = {:f};".format(ONE_4PI_EPS0)  # already in OpenMM units

        # Create CustomNonbondedForce.
        super(SwitchedReactionFieldForce, self).__init__(energy_expression)

        # Add parameters.
        self.addPerParticleParameter("charge")

        # Configure force.
        self.setNonbondedMethod(openmm.CustomNonbondedForce.CutoffPeriodic)
        self.setCutoffDistance(cutoff_distance)
        self.setUseLongRangeCorrection(False)
        if switch_width is not None:
            self.setUseSwitchingFunction(True)
            self.setSwitchingDistance(cutoff_distance - switch_width)
        else:  # Truncated
            self.setUseSwitchingFunction(False)

    @classmethod
    def from_nonbonded_force(cls, nonbonded_force, switch_width=1.0*unit.angstrom):
        """Copy constructor from an OpenMM `NonbondedForce`.

        The returned force has same cutoff distance and dielectric, and
        its particles have the same charges. Exclusions corresponding to
        `nonbonded_force` exceptions are also added.

        .. warning
            This only creates the force object. The electrostatics in
            `nonbonded_force` remains unmodified. Use the function
            `replace_reaction_field` to correctly convert a system to
            use an unshifted reaction field potential.

        Parameters
        ----------
        nonbonded_force : simtk.openmm.NonbondedForce
            The nonbonded force to copy.
        switch_width : simtk.unit.Quantity
            Switch width for electrostatics (units of distance).

        Returns
        -------
        reaction_field_force : UnshiftedReactionFieldForce
            The reaction field force with copied particles.

        """
        # OpenMM gives unitless values.
        cutoff_distance = nonbonded_force.getCutoffDistance()
        reaction_field_dielectric = nonbonded_force.getReactionFieldDielectric()
        reaction_field_force = cls(cutoff_distance, switch_width, reaction_field_dielectric)

        # Set particle charges.
        for particle_index in range(nonbonded_force.getNumParticles()):
            charge, sigma, epsilon = nonbonded_force.getParticleParameters(particle_index)
            reaction_field_force.addParticle([charge])

        # Add exclusions to CustomNonbondedForce.
        for exception_index in range(nonbonded_force.getNumExceptions()):
            iatom, jatom, chargeprod, sigma, epsilon = nonbonded_force.getExceptionParameters(exception_index)
            reaction_field_force.addExclusion(iatom, jatom)

        return reaction_field_force

    @classmethod
    def from_system(cls, system, switch_width=1.0*unit.angstrom):
        """Copy constructor from the first OpenMM `NonbondedForce` in `system`.

        If multiple `NonbondedForce`s are found, an exception is raised.

        .. warning
            This only creates the force object. The electrostatics in
            `nonbonded_force` remains unmodified. Use the function
            `replace_reaction_field` to correctly convert a system to
            use an unshifted reaction field potential.

        Parameters
        ----------
        system : simtk.openmm.System
            The system containing the nonbonded force to copy.
        switch_width : simtk.unit.Quantity
            Switch width for electrostatics (units of distance).

        Returns
        -------
        reaction_field_force : UnshiftedReactionFieldForce
            The reaction field force.

        Raises
        ------
        ValueError
            If multiple `NonbondedForce`s are found in the system.

        See Also
        --------
        UnshiftedReactionField.from_nonbonded_force

        """
        nonbonded_force = find_nonbonded_force(system)
        return cls.from_nonbonded_force(nonbonded_force, switch_width)

if __name__ == '__main__':
    import doctest
    doctest.testmod()
