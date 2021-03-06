"""
Unit and regression test for kissim.io.PocketBioPython class methods.

Note that class 
- methods (`from_structure_klifs_id`)
- attribute (`_residue_ids`, `residue_ixs`) and 
- property (`residues`)
are tested in test_io.py.
"""

from pathlib import Path

import pytest
import numpy as np
import pandas as pd
import Bio
from opencadd.databases.klifs import setup_local

from kissim.io import PocketBioPython

PATH_TEST_DATA = Path(__name__).parent / "kissim" / "tests" / "data"
LOCAL = setup_local(PATH_TEST_DATA / "KLIFS_download")


class TestPocketBioPython:
    """
    Test PocketBioPython class.
    """

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, n_atoms_complex, n_atoms_pocket",
        [(12347, LOCAL, 1819, 577)],
    )
    def test_data_complex(
        self, structure_klifs_id, klifs_session, n_atoms_complex, n_atoms_pocket
    ):
        """
        Test class attribute handling the complex data, i.e. `_data_complex`.
        """

        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        # Complex data
        assert isinstance(pocket_bp._data_complex, Bio.PDB.Chain.Chain)
        assert len(list(pocket_bp._data_complex.get_atoms())) == n_atoms_complex

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, n_hse_ca_complex, n_hse_cb_complex, n_hse_ca_pocket, n_hse_cb_pocket",
        [(12347, LOCAL, 246, 254, 75, 78)],
    )
    def test_hse_ca_cb(
        self,
        structure_klifs_id,
        klifs_session,
        n_hse_ca_complex,
        n_hse_cb_complex,
        n_hse_ca_pocket,
        n_hse_cb_pocket,
    ):
        """
        Test class
        - attributes (`_hse_ca_complex`, `_hse_cb_complex`) and
        - properties (`hse_ca`, `hse_cb`)
        regarding the HSExposure.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)

        # HSE for full complex
        assert isinstance(pocket_bp._hse_ca_complex, Bio.PDB.HSExposure.HSExposureCA)
        assert len(pocket_bp._hse_ca_complex) == n_hse_ca_complex
        assert isinstance(pocket_bp._hse_cb_complex, Bio.PDB.HSExposure.HSExposureCB)
        assert len(pocket_bp._hse_cb_complex) == n_hse_cb_complex
        # HSE for pocket only
        assert isinstance(pocket_bp.hse_ca, dict)
        assert len(pocket_bp.hse_ca) == n_hse_ca_pocket
        assert isinstance(pocket_bp.hse_cb, dict)
        assert len(pocket_bp.hse_cb) == n_hse_cb_pocket

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, pocket_centroid_mean",
        [(12347, LOCAL, 19.63254)],
    )
    def test_center(self, structure_klifs_id, klifs_session, pocket_centroid_mean):
        """
        Test the class property regarding the pocket centroid, i.e. `center`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)

        # Test property center
        assert isinstance(pocket_bp.center, Bio.PDB.vectors.Vector)
        assert pocket_bp.center.get_array().mean() == pytest.approx(pocket_centroid_mean)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, n_ca_atoms, n_ca_atoms_wo_na",
        [(12347, LOCAL, 85, 78)],
    )
    def test_ca_atoms(self, structure_klifs_id, klifs_session, n_ca_atoms, n_ca_atoms_wo_na):
        """
        Test the class property regarding the pocket's CA atoms, i.e. `ca_atoms`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)

        # Test property ca_atoms
        # Shape
        assert pocket_bp.ca_atoms.shape == (n_ca_atoms, 3)
        assert pocket_bp.ca_atoms.dropna(axis=0, subset=["residue.id"]).shape == (
            n_ca_atoms_wo_na,
            3,
        )
        # Columns and dtypes
        assert pocket_bp.ca_atoms.columns.to_list() == ["residue.id", "ca.atom", "ca.vector"]
        assert pocket_bp.ca_atoms.dtypes.to_list() == ["Int32", "object", "object"]
        for ca_atom in pocket_bp.ca_atoms["ca.atom"]:
            if ca_atom:
                assert isinstance(ca_atom, Bio.PDB.Atom.Atom)
        for ca_vector in pocket_bp.ca_atoms["ca.vector"]:
            if ca_vector:
                assert isinstance(ca_vector, Bio.PDB.vectors.Vector)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id, ca_atom_mean",
        [
            (5399, LOCAL, 1272, 18.5630),  # Residue has CA
            (5399, LOCAL, 1273, None),  # Residue has no CA
        ],
    )
    def test_ca_atom(self, structure_klifs_id, klifs_session, residue_id, ca_atom_mean):
        """
        Test if CA atom is retrieved correctly from a residue ID (test if-else cases),
        i.e. `_ca_atom` method.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        ca_atom_calculated = pocket_bp._ca_atom(residue_id)

        # Check CA atom mean
        if ca_atom_mean:
            assert isinstance(ca_atom_calculated, Bio.PDB.Atom.Atom)
            ca_atom_mean_calculated = ca_atom_calculated.get_vector().get_array().mean()
            assert ca_atom_mean == pytest.approx(ca_atom_mean_calculated)
        else:
            assert ca_atom_mean == ca_atom_calculated

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session",
        [(12347, LOCAL)],
    )
    def test_pcb_atoms(self, structure_klifs_id, klifs_session):
        """
        Test the class property regarding the pocket's pCB atoms, i.e. `pcb_atoms`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)

        # Test property pcb_atoms
        # Shape
        assert pocket_bp.pcb_atoms.shape == (85, 2)
        # Columns and dtypes
        assert pocket_bp.pcb_atoms.columns.to_list() == ["residue.id", "pcb.vector"]
        assert pocket_bp.pcb_atoms.dtypes.to_list() == ["Int32", "object"]
        for pcb_vector in pocket_bp.pcb_atoms["pcb.vector"]:
            if pcb_vector is not None:
                assert isinstance(pcb_vector, Bio.PDB.vectors.Vector)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id, pcb_atom_mean",
        [(9122, LOCAL, 272, 0.706664)],  # GLY
    )
    def test_pcb_atom_from_gly(self, structure_klifs_id, klifs_session, residue_id, pcb_atom_mean):
        """
        Test pseudo-CB calculation for GLY, i.e. method `_pcb_atom_from_gly`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        residue = pocket_bp._residue_from_residue_id(residue_id)

        # Check pCB atom mean
        pcb_atom_calculated = pocket_bp._pcb_atom_from_gly(residue)
        pcb_atom_mean_calculated = pcb_atom_calculated.get_array().mean()
        assert pcb_atom_mean == pytest.approx(pcb_atom_mean_calculated)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id",
        [(9122, LOCAL, 272)],  # GLY
    )
    def test_pcb_atom_from_non_gly(self, structure_klifs_id, klifs_session, residue_id):
        """
        Test that this method will not be used for GLY.
        """

        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        residue = pocket_bp._residue_from_residue_id(residue_id)
        with pytest.raises(ValueError):
            pocket_bp._pcb_atom_from_non_gly(residue)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id",
        [
            (9122, LOCAL, 337),  # ALA
            (9122, LOCAL, 357),  # Non-standard residue
        ],
    )
    def test_pcb_atom_from_gly_valueerror(self, structure_klifs_id, klifs_session, residue_id):
        """
        Test exceptions in pseudo-CB calculation for GLY, i.e. method `_pcb_atom_from_gly`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        residue = pocket_bp._residue_from_residue_id(residue_id)

        with pytest.raises(ValueError):
            pocket_bp._pcb_atom_from_gly(residue)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id, pcb_atom",
        [
            (9122, LOCAL, 272, np.array([12.223623, 8.544623, 32.441623])),  # GLY
            (
                9122,
                LOCAL,
                337,
                np.array([4.887966, 11.028965, 42.998965]),
            ),  # Residue with +- residue
            (9122, LOCAL, 261, None),  # Residue without + residue
            (9122, LOCAL, None, None),  # Residue is None
        ],
    )
    def test_pcb_atom(self, structure_klifs_id, klifs_session, residue_id, pcb_atom):
        """
        Test pseudo-CB calculation for a residue, i.e. method `_pcb_atom`.
        """

        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        pcb_atom_calculated = pocket_bp._pcb_atom(residue_id)

        if pcb_atom is None:
            assert pcb_atom_calculated is None
        else:
            pcb_atom_calculated = pcb_atom_calculated.get_array()
            assert pcb_atom[0] == pytest.approx(pcb_atom_calculated[0])
            assert pcb_atom[1] == pytest.approx(pcb_atom_calculated[1])
            assert pcb_atom[2] == pytest.approx(pcb_atom_calculated[2])

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session",
        [(12347, LOCAL)],
    )
    def test_side_chain_representatives(self, structure_klifs_id, klifs_session):
        """
        Test the class property regarding the pocket's side chain representatives,
        i.e. `side_chain_representatives`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        assert isinstance(pocket_bp.side_chain_representatives, pd.DataFrame)

        # Test property side_chain_representatives
        # Columns and dtypes
        assert pocket_bp.side_chain_representatives.columns.to_list() == [
            "residue.id",
            "sc.atom",
            "sc.vector",
        ]
        assert pocket_bp.side_chain_representatives.dtypes.to_list() == [
            "Int32",
            "object",
            "object",
        ]
        for sc_atom in pocket_bp.side_chain_representatives["sc.atom"]:
            if sc_atom is not None:
                assert isinstance(sc_atom, Bio.PDB.Atom.Atom)
        for sc_vector in pocket_bp.side_chain_representatives["sc.vector"]:
            if sc_vector is not None:
                assert isinstance(sc_vector, Bio.PDB.vectors.Vector)

    @pytest.mark.parametrize(
        "structure_klifs_id, klifs_session, residue_id, sc_atom_mean",
        [
            (9122, LOCAL, 272, None),  # GLY
            (9122, LOCAL, 337, 20.31),  # ALA (with CB)
            (1641, LOCAL, 19, None),  # ALA (without CB)
            (9122, LOCAL, 336, 22.122666),  # PHE (with CZ)
            (9122, LOCAL, 357, 27.526666),  # MSE > MET (with CE)
        ],
    )
    def test_side_chain_representative(
        self, structure_klifs_id, klifs_session, residue_id, sc_atom_mean
    ):
        """
        Test if side chain representative is retrieved correctly from a residue,
        i.e. method `_side_chain_representative`.
        """
        pocket_bp = PocketBioPython.from_structure_klifs_id(structure_klifs_id, klifs_session)
        sc_atom_calculated = pocket_bp._side_chain_representative(residue_id)

        # Check side chain representative mean
        if sc_atom_mean is not None:
            assert isinstance(sc_atom_calculated, Bio.PDB.Atom.Atom)
            sc_atom_mean_calculated = sc_atom_calculated.get_vector().get_array().mean()
            assert sc_atom_mean == pytest.approx(sc_atom_mean_calculated)
        else:
            assert sc_atom_calculated == None
