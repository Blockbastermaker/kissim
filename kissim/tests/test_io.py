"""
Unit and regression test for kissim.io class methods.
"""

from pathlib import Path
import pytest

import Bio
import pandas as pd

from kissim.io import BiopythonStructure, Mol2ToBiopythonStructure


PATH_TEST_DATA = Path(__name__).parent / "kissim" / "tests" / "data"


class TestBiopythonStructure:
    """
    Test BiopythonStructure class.
    """

    @pytest.mark.parametrize(
        "filepath",
        [
            PATH_TEST_DATA
            / "KLIFS_download"
            / "HUMAN"
            / "AAK1"
            / "4wsq_altA_chainA"
            / "pocket.mol2"
        ],
    )
    def test_from_file(self, filepath):
        """
        Test if Bio.PDB.Structure.Structure is set correctly. 
        """

        bpy = BiopythonStructure()
        structure = bpy.from_file(filepath)
        assert isinstance(structure, Bio.PDB.Structure.Structure)


class TestsMol2ToBiopythonStructure:
    """
    Test Mol2ToBiopythonStructure class.
    """

    @pytest.mark.parametrize(
        "filepath",
        [
            PATH_TEST_DATA
            / "KLIFS_download"
            / "HUMAN"
            / "AAK1"
            / "4wsq_altA_chainA"
            / "pocket.mol2"
        ],
    )
    def test_from_file(self, filepath):
        """
        Test if Bio.PDB.Structure.Structure is set correctly. 
        """

        bpy = Mol2ToBiopythonStructure()
        structure = bpy.from_file(filepath)

        assert isinstance(structure, Bio.PDB.Structure.Structure)
        model = structure[""]
        assert isinstance(model, Bio.PDB.Model.Model)
        chain = structure[""][""]
        assert isinstance(chain, Bio.PDB.Chain.Chain)
        residue = [i for i in structure[""][""].get_residues()][0]
        assert isinstance(residue, Bio.PDB.Residue.Residue)
        atom = [i for i in structure[""][""].get_atoms()][0]
        assert isinstance(atom, Bio.PDB.Atom.Atom)

    @pytest.mark.parametrize(
        "dataframe",
        [
            pd.DataFrame(
                [
                    ["1", "GLY", " ", "CA", 1.0, 1.0, 1.0],
                    ["1", "GLY", " ", "N", 2.0, 2.0, 2.0],
                    ["2", "ALA", " ", "CA", 3.0, 3.0, 3.0],
                ],
                columns=[
                    "residue.pdb_id",
                    "residue.name",
                    "residue.insertion",
                    "atom.name",
                    "atom.x",
                    "atom.y",
                    "atom.z",
                ],
            )
        ],
    )
    def test_from_dataframe(self, dataframe):
        """
        Test if Bio.PDB.Structure.Structure is set correctly. 
        """

        bpy = Mol2ToBiopythonStructure()
        structure = bpy.from_dataframe(dataframe)

        assert isinstance(structure, Bio.PDB.Structure.Structure)

    @pytest.mark.parametrize(
        "residue_pdb_ids, residue_pdb_ids_out, residue_insertions_out",
        [
            (
                ["_12", "_12", "_5", "_5", "_4A", "3", "33A", "_40", "50"],
                [-12, -12, -5, -5, -4, 3, 33, 40, 50],
                [" ", " ", " ", " ", "A", " ", "A", " ", " "],
            )
        ],
    )
    def test_format_dataframe(self, residue_pdb_ids, residue_pdb_ids_out, residue_insertions_out):
        """
        Test if the DataFrame created from the mol2 input file is formatted correctly.
        """

        dataframe = pd.DataFrame([residue_pdb_ids], index=["residue.pdb_id"]).transpose()

        bpy = Mol2ToBiopythonStructure()
        dataframe = bpy._format_dataframe(dataframe)

        assert dataframe["residue.pdb_id"].to_list() == residue_pdb_ids_out
        assert dataframe["residue.insertion"].to_list() == residue_insertions_out

    @pytest.mark.parametrize(
        "dataframe, residue_names, residue_pdb_ids",
        [
            (
                pd.DataFrame(
                    [
                        ["1", "GLY", " ", "CA", 1.0, 1.0, 1.0],
                        ["1", "GLY", " ", "N", 2.0, 2.0, 2.0],
                        ["2", "ALA", " ", "CA", 3.0, 3.0, 3.0],
                    ],
                    columns=[
                        "residue.pdb_id",
                        "residue.name",
                        "residue.insertion",
                        "atom.name",
                        "atom.x",
                        "atom.y",
                        "atom.z",
                    ],
                ),
                ["GLY", "ALA"],
                [(" ", "1", " "), (" ", "2", " ")],
            )
        ],
    )
    def test_chain(self, dataframe, residue_names, residue_pdb_ids):
        """
        Test if Bio.PDB.Chain.Chain is set correctly.
        """

        bpy = Mol2ToBiopythonStructure()
        chain = bpy._chain(dataframe)

        assert isinstance(chain, Bio.PDB.Chain.Chain)
        assert [residue.get_resname() for residue in chain.get_residues()] == residue_names
        assert [residue.get_id() for residue in chain.get_residues()] == residue_pdb_ids

    @pytest.mark.parametrize(
        "residue_name, residue_pdb_id, residue_insertion, residue_id",
        [
            ("ALA", 33, "A", (" ", 33, "A")),
            ("XXX", 33, "A", ("H_XXX", 33, "A")),
            ("HOH", 33, " ", ("W", 33, " ")),
        ],
    )
    def test_residue(self, residue_name, residue_pdb_id, residue_insertion, residue_id):
        """
        Test if Bio.PDB.Residue.Residue is set correctly.
        """

        bpy = Mol2ToBiopythonStructure()
        residue = bpy._residue(residue_name, residue_pdb_id, residue_insertion)

        assert isinstance(residue, Bio.PDB.Residue.Residue)
        assert residue.get_id() == residue_id
        assert residue.get_resname() == residue_name

    @pytest.mark.parametrize("name, x, y, z", [("CA", 1, 2, 3)])
    def test_atom(self, name, x, y, z):
        """
        Test if Bio.PDB.Atom.Atom is set correctly.
        """

        bpy = Mol2ToBiopythonStructure()
        atom = bpy._atom(name, x, y, z)

        assert isinstance(atom, Bio.PDB.Atom.Atom)
        assert atom.get_name() == name
        assert atom.get_coord()[0] == x
        assert atom.get_coord()[1] == y
        assert atom.get_coord()[2] == z
