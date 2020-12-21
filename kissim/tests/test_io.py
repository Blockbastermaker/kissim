"""
Unit and regression test for kissim.io class functionalities that
PocketBioPython and PocketDataFrame have in common.
"""

import pytest
import numpy as np
import pandas as pd
import Bio
from opencadd.databases.klifs import setup_remote

from kissim.io import PocketBioPython, PocketDataFrame

REMOTE = setup_remote()


class TestPocketBioPython:
    """
    Test common functionalities in the PocketBioPython and PocketDataFrame classes.
    """

    @pytest.mark.parametrize(
        "pocket_class, structure_id, remote",
        [(PocketBioPython, 12347, None), (PocketDataFrame, 12347, REMOTE)],
    )
    def test_from_structure_klifs_id(self, pocket_class, structure_id, remote):
        """
        Test if PocketBioPython can be set remotely (from_structure_klifs_id()).
        Test attribute `name`.
        """
        pocket = pocket_class.from_structure_klifs_id(structure_id, klifs_session=remote)
        assert isinstance(pocket, pocket_class)

        # Test attribute name
        assert pocket.name == structure_id

    @pytest.mark.parametrize(
        "pocket_class, structure_id, remote, n_residues, n_residues_wo_na, residue_ids_sum, residue_ixs_sum",
        [
            (PocketBioPython, 12347, REMOTE, 85, 78, 41198, 3655),
            (PocketDataFrame, 12347, REMOTE, 85, 78, 41198, 3655),
        ],
    )
    def test_residues(
        self,
        pocket_class,
        structure_id,
        remote,
        n_residues,
        n_residues_wo_na,
        residue_ids_sum,
        residue_ixs_sum,
    ):
        """
        Test the class
        - attribute (`_residue_ids`, `residue_ixs`) and
        - property (`residues`)
        regarding the residue IDs.
        """
        pocket = pocket_class.from_structure_klifs_id(structure_id, klifs_session=remote)
        # Test property residues
        assert isinstance(pocket.residues, pd.DataFrame)
        assert len(pocket.residues) == n_residues
        assert len(pocket.residues.dropna(axis=0, subset=["residue.id"])) == n_residues_wo_na
        assert pocket.residues["residue.id"].sum() == residue_ids_sum
        assert pocket.residues["residue.ix"].sum() == residue_ixs_sum

        # Test attribute _residue_ids
        assert isinstance(pocket._residue_ids[0], int)
        assert len(pocket._residue_ids) == n_residues
        assert sum([i for i in pocket._residue_ids if i]) == residue_ids_sum

        # Test attribute _residue_ix
        assert isinstance(pocket._residue_ixs[0], int)
        assert len(pocket._residue_ixs) == n_residues
        assert sum([i for i in pocket._residue_ixs if i]) == residue_ixs_sum
