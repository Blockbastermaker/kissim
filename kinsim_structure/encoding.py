"""
encoding.py

Subpocket-based structural fingerprint for kinase pocket comparison.

Handles the primary functions for the structural kinase fingerprint encoding.
"""

import logging

from Bio.PDB import HSExposureCA, HSExposureCB, Selection, Vector
from Bio.PDB import calc_angle
import nglview as nv
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.special import cbrt
from scipy.stats.stats import moment

from kinsim_structure.auxiliary import KlifsMoleculeLoader, PdbChainLoader
from kinsim_structure.auxiliary import center_of_mass, split_klifs_code

logger = logging.getLogger(__name__)


FEATURE_NAMES = [
    'size',
    'hbd',
    'hba',
    'charge',
    'aromatic',
    'aliphatic',
    'sca',
    'exposure',
    'distance_to_centroid',
    'distance_to_hinge_region',
    'distance_to_dfg_region',
    'distance_to_front_pocket'
]

ANCHOR_RESIDUES = {
    'hinge_region': [16, 47, 80],
    'dfg_region': [19, 24, 81],
    'front_pocket': [6, 48, 75]
}  # Are the same as in Eva's implementation

# KLIFS IDs for hinge/DFG region (taken from KLIFS website)
HINGE_KLIFS_IDS = [46, 47, 48]
DFG_KLIFS_IDS = [81, 82, 83]

FEATURE_LOOKUP = {
    'size': {
        1: 'ALA CYS GLY PRO SER THR VAL'.split(),
        2: 'ASN ASP GLN GLU HIS ILE LEU LYS MET'.split(),
        3: 'ARG PHE TRP TYR'.split()
    },
    'hbd': {
        0: 'ALA ASP GLU GLY ILE LEU MET PHE PRO VAL'.split(),
        1: 'ASN CYS GLN HIS LYS SER THR TRP TYR'.split(),
        3: 'ARG'.split()
    },  # Note: it is correct that 2 is missing!
    'hba': {
        0: 'ALA ARG CYS GLY ILE LEU LYS MET PHE PRO TRP VAL'.split(),
        1: 'ASN GLN HIS SER THR TYR'.split(),
        2: 'ASP GLU'.split()
    },
    'charge': {
        -1: 'ASP GLU'.split(),
        0: 'ALA ASN CYS GLN GLY HIS ILE LEU MET PHE PRO SER TRP TYR VAL'.split(),
        1: 'ARG LYS THR'.split()
    },
    'aromatic': {
        0: 'ALA ARG ASN ASP CYS GLN GLU GLY ILE LEU LYS MET PRO SER THR VAL'.split(),
        1: 'HIS PHE TRP TYR'.split()
    },
    'aliphatic': {
        0: 'ARG ASN ASP GLN GLU GLY HIS LYS PHE SER TRP TYR'.split(),
        1: 'ALA CYS ILE LEU MET PRO THR VAL'.split()
    }
}

STANDARD_AA = 'ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split()

MODIFIED_AA_CONVERSION = {
    'CAF': 'CYS',
    'CME': 'CYS',
    'CSS': 'CYS',
    'OCY': 'CYS',
    'KCX': 'LYS',
    'MSE': 'MET',
    'PHD': 'ASP',
    'PTR': 'TYR'
}

MEDIAN_SIDE_CHAIN_ANGLE = pd.read_csv(
    Path(__file__).parent / 'data' / 'side_chain_angle_mean_median.csv',
    index_col='residue_name'
)['sca_median']

EXPOSURE_RADIUS = 13.0

N_HEAVY_ATOMS = {
    'GLY': 0,
    'ALA': 1,
    'CYS': 2,
    'SER': 2,
    'PRO': 3,
    'THR': 3,
    'VAL': 3,
    'ASN': 4,
    'ASP': 4,
    'ILE': 4,
    'LEU': 4,
    'MET': 4,
    'GLN': 5,
    'GLU': 5,
    'LYS': 5,
    'HIS': 6,
    'ARG': 7,
    'PHE': 7,
    'TYR': 8,
    'TRP': 10
}

N_HEAVY_ATOMS_CUTOFF = {  # Number of heavy atoms needed for side chain centroid calculation (>75% coverage)
    'GLY': 0,
    'ALA': 1,
    'CYS': 2,
    'SER': 2,
    'PRO': 3,
    'THR': 3,
    'VAL': 3,
    'ASN': 3,
    'ASP': 3,
    'ILE': 3,
    'LEU': 3,
    'MET': 3,
    'GLN': 4,
    'GLU': 4,
    'LYS': 4,
    'HIS': 5,
    'ARG': 6,
    'PHE': 6,
    'TYR': 6,
    'TRP': 8
}


class Fingerprint:
    """
    Kinase fingerprint with 8 physicochemical and 4 spatial features for each residue in the KLIFS-defined
    kinase binding site of 85 pre-aligned residues.

    Physicochemical features:
    - Size
    - Pharmacophoric features: Hydrogen bond donor, hydrogen bond acceptor, aromatic, aliphatic and charge feature
    - Side chain angle
    - Half sphere exposure

    Spatial features:
    Distance of each residue to 4 reference points:
    - Binding site centroid
    - Hinge region
    - DFG region
    - Front pocket

    Two fingerprint types are offered:
    - Fingeprint type 1:
      8 physicochemical and 4 spatial (distance) features (columns) for 85 residues (rows)
      = 1020 bit fingerprint.
    - Fingerprint type 2 consisting of two parts:
      (i)  8 physicochemical features (columns) for 85 residues (rows)
           = 680 bit fingerprint
      (ii) 12 spatial features, i.e. first three moments for each of the 4 distance distributions over 85 residues
           = 12 bit fingerprint

    Attributes
    ----------
    molecule_code : str
        Molecule code as defined by KLIFS in mol2 file.
    fingerprint_type1 : pandas.DataFrame
        Fingerprint type 1.
    fingerprint_type2 : dict of pandas.DataFrame
        Fingerprint type 2.
    """

    def __init__(self):

        self.molecule_code = None
        self.fingerprint_type1 = None
        self.fingerprint_type2 = None
        self.fingerprint_type1_normalized = None
        self.fingerprint_type1_normalized = None

    def from_metadata_entry(self, klifs_metadata_entry):
        """
        Get kinase fingerprint from KLIFS metadata entry.

        Parameters
        ----------
        klifs_metadata_entry : pandas.Series
            KLIFS metadata describing a pocket entry in the KLIFS dataset.
        """

        klifs_molecule_loader = KlifsMoleculeLoader(klifs_metadata_entry=klifs_metadata_entry)
        molecule = klifs_molecule_loader.molecule

        pdb_chain_loader = PdbChainLoader(klifs_metadata_entry)
        chain = pdb_chain_loader.chain

        self.from_molecule(molecule, chain)

    def from_molecule(self, molecule, chain):
        """
        Get kinase fingerprint from molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        """

        self.molecule_code = molecule.code

        physicochemical_features = PhysicoChemicalFeatures()
        physicochemical_features.from_molecule(molecule, chain)

        spatial_features = SpatialFeatures()
        spatial_features.from_molecule(molecule)

        self.fingerprint_type1 = self._get_fingerprint_type1(physicochemical_features, spatial_features)
        self.fingerprint_type2 = self._get_fingerprint_type2()
        self.fingerprint_type1_normalized = self._normalize_fingerprint_type1()
        self.fingerprint_type2_normalized = self._normalize_fingerprint_type2()

    @staticmethod
    def _get_fingerprint_type1(physicochemical_features, spatial_features):

        features = pd.concat(
            [
                physicochemical_features.features[FEATURE_NAMES[:8]],
                spatial_features.features[FEATURE_NAMES[8:]]
            ],
            axis=1
        ).copy()

        # Bring all fingerprints to same dimensions (i.e. add currently missing residues in DataFrame)
        empty_df = pd.DataFrame([], index=range(1, 86))
        features = pd.concat([empty_df, features], axis=1)

        # Set all None to nan
        features.fillna(value=pd.np.nan, inplace=True)

        return features

    def _get_fingerprint_type2(self):

        if self.fingerprint_type1 is not None:

            physicochemical_bits = self.fingerprint_type1[FEATURE_NAMES[:8]]
            spatial_bits = self.fingerprint_type1[FEATURE_NAMES[8:]]

            moments = self._calc_moments(spatial_bits)

            return {
                'physchem': physicochemical_bits,
                'moments': moments
            }

    def _normalize_fingerprint_type1(self):

        if self.fingerprint_type1 is not None:

            normalized_physchem = self._normalize_physicochemical_bits()
            normalized_distances = self._normalize_distances_bits()

            normalized = pd.concat(
                [normalized_physchem, normalized_distances],
                axis=1
            )

            return normalized

        else:
            return None

    def _normalize_fingerprint_type2(self):

        if self.fingerprint_type2 is not None:

            normalized_physchem = self.fingerprint_type1_normalized[FEATURE_NAMES[:8]]
            normalized_moments = self.fingerprint_type2['moments']  # TODO no normalization is done here, change this?

            normalized = {
                'physchem': normalized_physchem,
                'moments': normalized_moments
            }

            return normalized

        else:
            return None

    def _normalize_physicochemical_bits(self):

        # Make a copy of DataFrame
        normalized = self.fingerprint_type1[FEATURE_NAMES[:8]].copy()

        # Normalize size
        normalized['size'] = normalized['size'].apply(lambda x: (x - 1) / 2.0)

        # Normalize pharmacophoric features
        normalized['hbd'] = normalized['hbd'].apply(lambda x: x / 3.0)
        normalized['hba'] = normalized['hba'].apply(lambda x: x / 2.0)
        normalized['charge'] = normalized['charge'].apply(lambda x: (x + 1) / 2.0)
        normalized['aromatic'] = normalized['hba'].apply(lambda x: x / 1.0)
        normalized['aliphatic'] = normalized['hba'].apply(lambda x: x / 1.0)

        # Normalize side chain angle
        normalized['sca'] = normalized['sca'].apply(lambda x: x / 180.0)

        # Normalize exposure
        normalized['exposure'] = normalized['exposure'].apply(lambda x: x / 1)

        return normalized

    def _normalize_distances_bits(self):

        # Make a copy of DataFrame
        normalized = self.fingerprint_type1[FEATURE_NAMES[8:]].copy()

        # Normalize distances
        distance_normalizer = 35.0

        normalized['distance_to_centroid'] = normalized['distance_to_centroid'].apply(
            lambda x: x / distance_normalizer if x <= distance_normalizer or np.isnan(x) else 1.0
        )
        normalized['distance_to_hinge_region'] = normalized['distance_to_hinge_region'].apply(
            lambda x: x / distance_normalizer if x <= distance_normalizer or np.isnan(x) else 1.0
        )
        normalized['distance_to_dfg_region'] = normalized['distance_to_dfg_region'].apply(
            lambda x: x / distance_normalizer if x <= distance_normalizer or np.isnan(x) else 1.0
        )
        normalized['distance_to_front_pocket'] = normalized['distance_to_front_pocket'].apply(
            lambda x: x / distance_normalizer if x <= distance_normalizer or np.isnan(x) else 1.0
        )

        if not (normalized.iloc[:, 1:12].fillna(0) <= 1).any().any():
            raise ValueError(f'Normalization failed for {self.molecule_code}: Values greater 1!')

        return normalized

    def _normalize_moments_bits(self):

        return self.fingerprint_type2['moments']

    @staticmethod
    def _calc_moments(distances):
        """
        Calculate first, second, and third moment (mean, standard deviation, and skewness) for a distance distribution.
        Parameters
        ----------
        distances : pandas.DataFrame
            Distance distribution, i.e. distances from reference point to all representatives (points)
        Returns
        -------
        pandas.DataFrame
            First, second, and third moment of distance distribution.
        """

        # Get first, second, and third moment (mean, standard deviation, and skewness) for a distance distribution
        # Second and third moment: delta degrees of freedom = 0 (divisor N)
        if len(distances) > 0:
            m1 = distances.mean()
            m2 = distances.std(ddof=0)
            m3 = pd.Series(
                cbrt(
                    moment(
                        distances,
                        moment=3,
                        nan_policy='omit'
                    )
                ),
                index=distances.columns.tolist()
            )
        else:
            # In case there is only one data point.
            # However, this should not be possible due to restrictions in get_shape function.
            logger.info(f'Only one data point available for moment calculation, thus write None to moments.')
            m1, m2, m3 = pd.np.nan, pd.np.nan, pd.np.nan

        # Store all moments in DataFrame
        moments = pd.concat([m1, m2, m3], axis=1)
        moments.columns = ['moment1', 'moment2', 'moment3']

        return moments


class PhysicoChemicalFeatures:
    """
    Physicochemical features for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.

    Physicochemical properties:
    - Size
    - Pharmacophoric features: Hydrogen bond donor, hydrogen bond acceptor, aromatic, aliphatic and charge feature
    - Side chain angle
    - Half sphere exposure

    Attributes
    ----------
    features : pandas.DataFrame
        6 features (columns) for 85 residues (rows).
    """

    def __init__(self):

        self.features = None

    def from_molecule(self, molecule, chain):
        """
        Get physicochemical properties for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        """

        pharmacophore_size = PharmacophoreSizeFeatures()
        pharmacophore_size.from_molecule(molecule)

        side_chain_angle = SideChainAngleFeature()
        side_chain_angle.from_molecule(molecule, chain)

        exposure = ExposureFeature()
        exposure.from_molecule(molecule, chain)

        # Concatenate all physicochemical features
        physicochemical_features = pd.concat(
            [
                pharmacophore_size.features,
                side_chain_angle.features,
                exposure.features
            ],
            axis=1
        )

        self.features = physicochemical_features


class SpatialFeatures:
    """
    Spatial features for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.

    Spatial properties:
    Distance of each residue to 4 reference points:
    - Binding site centroid
    - Hinge region
    - DFG region
    - Front pocket

    Attributes
    ----------
    reference_points : pandas.DataFrame
        Coordiantes (rows) for 4 reference points (columns).
    features : pandas.DataFrame
        4 features (columns) for 85 residues (rows).
    """

    def __init__(self):

        self.reference_points = None
        self.features = None

    def from_molecule(self, molecule):
        """
        Get spatial properties for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        """

        # Get reference points
        self.reference_points = self.get_reference_points(molecule)

        # Get all residues' CA atoms in molecule (set KLIFS position as index)
        residues_ca = molecule.df[molecule.df.atom_name == 'CA']['klifs_id x y z'.split()]
        residues_ca.set_index('klifs_id', drop=True, inplace=True)

        distances = {}

        for name, coord in self.reference_points.items():

            # If any reference points coordinate is None, set also distance to None

            if coord.isna().any():
                distances[f'distance_to_{name}'] = None
            else:
                distance = (residues_ca - coord).transpose().apply(lambda x: np.linalg.norm(x))
                distance.rename(name, inplace=True)
                distances[f'distance_to_{name}'] = np.round(distance, 2)

        self.features = pd.DataFrame.from_dict(distances)

    def get_reference_points(self, molecule):
        """
        Get reference points of a molecule, i.e. the binding site centroid, hinge region, DFG region and front pocket.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.

        Returns
        -------
        pandas.DataFrame
            Coordiantes (rows) for 4 reference points (columns).
        """

        reference_points = dict()

        # Calculate centroid-based reference point:
        # Calculate mean of all CA atoms
        reference_points['centroid'] = molecule.df[molecule.df.atom_name == 'CA']['x y z'.split()].mean()

        # Calculate anchor-based reference points:
        # Get anchor atoms for each anchor-based reference point
        anchors = self.get_anchor_atoms(molecule)

        for reference_point_name, anchor_atoms in anchors.items():

            # If any anchor atom None, set also reference point coordinates to None
            if anchor_atoms.isna().values.any():
                reference_points[reference_point_name] = [None, None, None]
            else:
                reference_points[reference_point_name] = anchor_atoms.mean()

        return pd.DataFrame.from_dict(reference_points)

    @staticmethod
    def get_anchor_atoms(molecule):
        """
        For each anchor-based reference points (i.e. hinge region, DFG region and front pocket)
        get the three anchor (i.e. CA) atoms.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.

        Returns
        -------
        dict of pandas.DataFrames
            Coordinates (x, y, z) of the three anchor atoms (rows=anchor residue KLIFS ID x columns=coordinates) for
            each of the anchor-based reference points.
        """

        anchors = dict()

        # Calculate anchor-based reference points
        # Process each reference point: Collect anchor residue atoms and calculate their mean
        for reference_point_name, anchor_klifs_ids in ANCHOR_RESIDUES.items():

            anchor_atoms = []

            # Process each anchor residue: Get anchor atom
            for anchor_klifs_id in anchor_klifs_ids:

                # Select anchor atom, i.e. CA atom of KLIFS ID (anchor residue)
                anchor_atom = molecule.df[
                    (molecule.df.klifs_id == anchor_klifs_id) &
                    (molecule.df.atom_name == 'CA')
                ]

                # If this anchor atom exists, append to anchor atoms list
                if len(anchor_atom) == 1:
                    anchor_atom.set_index('klifs_id', inplace=True)
                    anchor_atom.index.name = None
                    anchor_atoms.append(anchor_atom[['x', 'y', 'z']])

                # If this anchor atom does not exist, do workarounds
                elif len(anchor_atom) == 0:

                    # Do residues (and there CA atoms) exist next to anchor residue?
                    atom_before = molecule.df[
                        (molecule.df.klifs_id == anchor_klifs_id - 1) &
                        (molecule.df.atom_name == 'CA')
                        ]
                    atom_after = molecule.df[
                        (molecule.df.klifs_id == anchor_klifs_id + 1) &
                        (molecule.df.atom_name == 'CA')
                        ]
                    atom_before.set_index('klifs_id', inplace=True, drop=False)
                    atom_after.set_index('klifs_id', inplace=True, drop=False)

                    # If both neighboring CA atoms exist, get their mean as alternative anchor atom
                    if len(atom_before) == 1 and len(atom_after) == 1:
                        anchor_atom_alternative = pd.concat([atom_before, atom_after])[['x', 'y', 'z']].mean()
                        anchor_atom_alternative = pd.DataFrame({anchor_klifs_id: anchor_atom_alternative}).transpose()
                        anchor_atoms.append(anchor_atom_alternative)

                    elif len(atom_before) == 1 and len(atom_after) == 0:
                        atom_before.set_index('klifs_id', inplace=True)
                        anchor_atoms.append(atom_before[['x', 'y', 'z']])

                    elif len(atom_after) == 1 and len(atom_before) == 0:
                        atom_after.set_index('klifs_id', inplace=True)
                        anchor_atoms.append(atom_after[['x', 'y', 'z']])

                    else:
                        atom_missing = pd.DataFrame.from_dict(
                            {anchor_klifs_id: [None, None, None]},
                            orient='index',
                            columns='x y z'.split()
                        )
                        anchor_atoms.append(atom_missing)

                # If there are several anchor atoms, something's wrong...
                else:
                    raise ValueError(f'Too many anchor atoms for'
                                     f'{molecule.code}, {reference_point_name}, {anchor_klifs_id}: '
                                     f'{len(anchor_atom)} (one atom allowed).')

            anchors[reference_point_name] = pd.concat(anchor_atoms)

        return anchors

    @staticmethod
    def save_cgo_refpoints(klifs_metadata_entry, output_path):
        """
        Save CGO PyMol file showing a kinase with anchor residues, reference points and highlighted hinge and DFG
        region.

        Parameters
        ----------
        klifs_metadata_entry : pandas.Series
            KLIFS metadata describing a pocket entry in the KLIFS dataset.
        output_path : str or pathlib.Path
            Path to directory where data file should be saved.
        """

        output_path = Path(output_path)

        # PyMol sphere colors (for reference points)
        sphere_colors = {
            'centroid': [1.0, 0.65, 0.0],  # orange
            'hinge_region': [1.0, 0.0, 1.0],  # magenta
            'dfg_region': [0.25, 0.41, 0.88],  # skyblue
            'front_pocket': [0.0, 1.0, 0.0]  # green
        }

        # Load molecule from KLIFS metadata entry
        klifs_molecule_loader = KlifsMoleculeLoader(klifs_metadata_entry=klifs_metadata_entry)
        molecule = klifs_molecule_loader.molecule

        # Path to molecule file
        mol2_path = klifs_molecule_loader.file_from_metadata_entry(klifs_metadata_entry)

        # Output path
        Path(output_path).mkdir(parents=True, exist_ok=True)

        # Mol2 residue IDs for hinge/DFG region
        hinge_mol2_ids = molecule.df[molecule.df.klifs_id.isin(HINGE_KLIFS_IDS)].res_id.unique()
        dfg_mol2_ids = molecule.df[molecule.df.klifs_id.isin(DFG_KLIFS_IDS)].res_id.unique()

        # Get reference points and anchor atoms (coordinates)
        space = SpatialFeatures()
        space.from_molecule(molecule)
        ref_points = space.reference_points.transpose()
        anchor_atoms = space.get_anchor_atoms(molecule)

        # Drop missing reference points and anchor atoms
        ref_points.dropna(axis=0, how='any', inplace=True)
        for ref_point_name, anchor_atoms_per_ref_point in anchor_atoms.items():
            anchor_atoms_per_ref_point.dropna(axis=0, how='any', inplace=True)

        # Collect all text lines to be written to file
        lines = []

        # Set descriptive PyMol object name for reference points
        obj_name = f'refpoints_{molecule.code[6:]}'

        # Imports
        lines.append('from pymol import *')
        lines.append('import os')
        lines.append('from pymol.cgo import *\n')

        # Load pocket structure
        lines.append(f'cmd.load("{mol2_path}", "pocket_{molecule.code[6:]}")\n')
        lines.append(f'cmd.show("cartoon", "pocket_{molecule.code[6:]}")')
        lines.append(f'cmd.hide("lines", "pocket_{molecule.code[6:]}")')
        lines.append(f'cmd.color("gray", "pocket_{molecule.code[6:]}")\n')
        lines.append(f'cmd.set("cartoon_transparency", 0.5, "pocket_{molecule.code[6:]}")')
        lines.append(f'cmd.set("opaque_background", "off")\n')

        # Color hinge and DFG region
        lines.append(f'cmd.set_color("hinge_color", {sphere_colors["hinge_region"]})')
        lines.append(f'cmd.set_color("dfg_color", {sphere_colors["dfg_region"]})')
        lines.append(f'cmd.color("hinge_color", "pocket_{molecule.code[6:]} and resi {"+".join([str(i) for i in hinge_mol2_ids])}")')
        lines.append(f'cmd.color("dfg_color", "pocket_{molecule.code[6:]} and resi {"+".join([str(i) for i in dfg_mol2_ids])}")\n')

        # Add spheres, i.e. reference points and anchor atoms
        lines.append(f'obj_{obj_name} = [\n')  # Variable cannot start with digit, thus add prefix obj_

        # Reference points
        for ref_point_name, ref_point in ref_points.iterrows():

            # Set and write sphere color to file
            lines.append(
                f'\tCOLOR, '
                f'{str(sphere_colors[ref_point_name][0])}, '
                f'{str(sphere_colors[ref_point_name][1])}, '
                f'{str(sphere_colors[ref_point_name][2])},'
            )

            # Write reference point coordinates and size to file
            lines.append(
                f'\tSPHERE, '
                f'{str(ref_point["x"])}, '
                f'{str(ref_point["y"])}, '
                f'{str(ref_point["z"])}, '
                f'{str(1)},'
            )

            # Write anchor atom coordinates and size to file
            if ref_point_name != 'centroid':
                for anchor_atom_index, anchor_atom in anchor_atoms[ref_point_name].iterrows():
                    lines.append(
                        f'\tSPHERE, '
                        f'{str(anchor_atom["x"])}, '
                        f'{str(anchor_atom["y"])}, '
                        f'{str(anchor_atom["z"])}, '
                        f'{str(0.5)},'
                    )

        # Write command to file that will load the reference points as PyMol object
        lines.append(f']\n')

        # Add KLIFS IDs to CA atoms as labels

        for res_id, klifs_id in zip(molecule.df.res_id.unique(), molecule.df.klifs_id.unique()):
            lines.append(
                f'cmd.label(selection="pocket_{molecule.code[6:]} and name CA and resi {res_id}", expression="\'{klifs_id}\'")'

            )

        lines.append(f'\ncmd.load_cgo(obj_{obj_name}, "{obj_name}")')

        with open(output_path / f'refpoints_{molecule.code[6:]}.py', 'w') as f:
            f.write('\n'.join(lines))

        # In PyMol enter the following to save png
        # PyMOL > ray 900, 900
        # PyMOL > save refpoints.png


class SideChainOrientationFeature:
    """
    Side chain orientation for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.
    Side chain orientation of a residue is defined by the vertex angle formed by (i) the residue's CA atom,
    (ii) the residue's side chain centroid, and (iii) the pocket centroid (calculated based on its CA atoms), whereby
    the CA atom forms the vertex.

    Attributes
    ----------
    features : pandas.DataFrame
        1 feature, i.e. side chain orientation, (column) for 85 residues (rows).
    features_verbose : pandas.DataFrame
        Feature, Ca, Cb, and centroid vectors as well as metadata information (columns) for 85 residues (row).
    code : str
        KLIFS code.
    vector_pocket_centroid : Bio.PDB.Vector.Vector
        Vector to pocket centroid.
    """

    def __init__(self):

        self.features = None
        self.features_verbose = None
        self.code = None  # Necessary for cgo generation
        self.vector_pocket_centroid = None  # Necessary to not calculate pocket centroid for each residue again

    def from_molecule(self, molecule, chain):
        """
        Get side chain orientation for each residue in a molecule (pocket).
        Side chain orientation of a residue is defined by the vertex angle formed by (i) the residue's CA atom,
        (ii) the residue's side chain centroid,  and (iii) the pocket centroid (calculated based on its CA atoms),
        whereby the CA atom forms the vertex.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        """

        self.code = molecule.code

        # Get pocket residues
        pocket_residues = self._get_pocket_residues(molecule, chain)

        # Get vectors (for each residue CA atoms, side chain centroid, pocket centroid)
        pocket_vectors = self._get_pocket_vectors(pocket_residues)

        # Get vertex angles (for each residue, vertex angle between aforementioned points)
        vertex_angles = self._get_vertex_angles(pocket_vectors)

        # Store vertex angles
        self.features = vertex_angles
        # Store vertex angles plus vectors and metadata
        self.features_verbose = pd.concat([pocket_vectors, vertex_angles], axis=1)

    @staticmethod
    def _get_pocket_residues(molecule, chain):
        """
        Get KLIFS pocket residues from PDB structural data: Bio.PDB.Residue.Residue plus metadata, i.e. KLIFS residue
        ID, PDB residue ID, and residue name for all pocket residues.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.

        Returns
        -------
        pandas.DataFrame
            Pocket residues: Bio.PDB.Residue.Residue plus metadata, i.e. KLIFS residue ID, PDB residue ID, and residue
            name (columns) for all pocket residues (rows).
        """

        # Get KLIFS pocket metadata, e.g. PDB residue IDs from mol2 file (DataFrame)
        pocket_residues = pd.DataFrame(
            molecule.df.groupby('klifs_id res_id res_name'.split()).groups.keys(),
            columns='klifs_id res_id res_name'.split()

        )
        pocket_residues.set_index('klifs_id', drop=False, inplace=True)

        # Select residues from chain based on PDB residue IDs and add to DataFrame
        pocket_residues['pocket_residues'] = [chain[res_id] for res_id in pocket_residues.res_id]

        return pocket_residues

    def _get_pocket_vectors(self, pocket_residues):
        """
        Get vectors to CA, residue side chain centroid, and pocket centroid.

        Parameters
        ----------
        pocket_residues : pandas.DataFrame
            Pocket residues: Bio.PDB.Residue.Residue plus metadata, i.e. KLIFS residue ID, PDB residue ID, and residue
            name (columns) for all pocket residues (rows).

        Returns
        -------
        pandas.DataFrame
            Vectors to CA, residue side chain centroid, and pocket centroid for each residue of a molecule, alongside
            with metadata on KLIFS residue ID, PDB residue ID, and residue name.
        """

        # Save here values per residue
        data = []

        # Calculate pocket centroid
        if not self.vector_pocket_centroid:
            self.vector_pocket_centroid = self._get_pocket_centroid(pocket_residues)

        # Calculate CA atom and side chain centroid
        for residue in pocket_residues.pocket_residues:

            vector_ca = self._get_ca(residue)
            vector_side_chain_centroid = self._get_side_chain_centroid(residue)

            data.append([vector_ca, vector_side_chain_centroid, self.vector_pocket_centroid])

        data = pd.DataFrame(
            data,
            index=pocket_residues.klifs_id,
            columns='ca side_chain_centroid pocket_centroid'.split()
        )

        metadata = pocket_residues['klifs_id res_id res_name'.split()]

        if len(metadata) != len(data):
            raise ValueError(f'DataFrames to be concatenated must be of same length: '
                             f'Metadata has {len(metadata)} rows, CA/CB/centroid data has {len(data)} rows.')

        return pd.concat([metadata, data], axis=1)

    @staticmethod
    def _get_vertex_angles(pocket_vectors):
        """
        Get vertex angles for residues' side chain orientations to the molecule (pocket) centroid.
        Side chain orientation of a residue is defined by the angle formed by (i) the residue's CB atom,
        (ii) the residue's side chain centroid, and (iii) the pocket centroid (calculated based on its CA atoms),
        whereby the CA atom forms the vertex.

        Parameters
        ----------
        pocket_vectors : pandas.DataFrame
            Vectors to CA, residue side chain centroid, and pocket centroid for each residue of a molecule, alongside
            with metadata on KLIFS residue ID, PDB residue ID, and residue name (columns) for 85 pocket residues.

        Returns
        -------
        pandas.DataFrame
            Side chain orientation feature (column) for 85 residues (rows).
        """

        side_chain_orientation = []

        for index, row in pocket_vectors.iterrows():

            # If all three vectors available, calculate angle - otherwise set angle to None

            if row.ca and row.side_chain_centroid and row.pocket_centroid:
                # Calculate vertex angle: CA atom is vertex
                angle = np.degrees(
                    calc_angle(
                        row.side_chain_centroid, row.ca, row.pocket_centroid
                    )
                )
                side_chain_orientation.append(angle.round(2))
            else:
                side_chain_orientation.append(None)

        # Cast to DataFrame
        side_chain_orientation = pd.DataFrame(
            side_chain_orientation,
            index=pocket_vectors.klifs_id,
            columns=['sco']
        )

        return side_chain_orientation

    @staticmethod
    def _get_ca(residue):
        """
        Get residue's CA atom.

        Parameters
        ----------
        residue : Bio.PDB.Residue.Residue
            Residue.

        Returns
        -------
        Bio.PDB.vectors.Vector or None
            Residue's CA vector.
        """

        atom_names = [atoms.fullname for atoms in residue.get_atoms()]

        # Set CA atom
        if 'CA' in atom_names:
            vector_ca = residue['CA'].get_vector()
        else:
            vector_ca = None

        return vector_ca

    @staticmethod
    def _get_side_chain_centroid(residue):
        """
        Get residue's side chain centroid.

        Parameters
        ----------
        residue : Bio.PDB.Residue.Residue
            Residue.

        Returns
        -------
        Bio.PDB.vectors.Vector or None
            Residue's side chain centroid.
        """

        # Select only atoms that are
        # - not part of the backbone
        # - not oxygen atoms (OXT) on the terminal carboxyl group
        # - not H atoms

        selected_atoms = [
            atom for atom in residue.get_atoms() if
            (atom.fullname not in 'N CA C O OXT'.split()) & (not atom.get_id().startswith('H'))
        ]

        # Set side chain centroid

        if len(selected_atoms) <= 1:  # Too few side chain atoms for centroid calculation
            return None

        try:  # If standard residue, calculate centroid only if enough side chain atoms available
            if len(selected_atoms) < N_HEAVY_ATOMS_CUTOFF[residue.get_resname()]:
                return None
            else:
                return Vector(center_of_mass(selected_atoms, geometric=True))

        except KeyError:  # If non-standard residue, use whatever side chain atoms available
            return Vector(center_of_mass(selected_atoms, geometric=True))

    @staticmethod
    def _get_pocket_centroid(pocket_residues):
        """
        Get centroid of pocket CA atoms.

        Parameters
        ----------
        pocket_residues : pandas.DataFrame
            Pocket residues: Bio.PDB.Residue.Residue plus metadata, i.e. KLIFS residue ID, PDB residue ID, and residue
            name (columns) for all pocket residues (rows).

        Returns
        -------
        Bio.PDB.vectors.Vector or None
            Pocket centroid.
        """

        ca_vectors = []

        for residue in pocket_residues.pocket_residues:
            try:
                ca_vectors.append(residue['CA'])
            except KeyError:
                pass

        try:
            return Vector(center_of_mass(ca_vectors, geometric=True))
        except ValueError:
            return None

    def save_cgo_side_chain_orientation(self, output_path):
        """
        Save CA atom, side chain centroid and pocket centroid as spheres and label CA atom with side chain orientation
        vertex angle value to PyMol cgo file.

        Parameters
        ----------
        output_path : pathlib.Path or str
            Path to output directory.
        """

        # Get molecule and molecule code
        code = split_klifs_code(self.code)

        # Get pocket residues
        pocket_residues_ids = list(self.features_verbose.res_id)

        # List contains lines for python script
        lines = [f'from pymol import *', f'import os', f'from pymol.cgo import *\n']

        # Fetch PDB, remove solvent, remove unnecessary chain(s) and residues
        lines.append(f'cmd.fetch("{code["pdb_id"]}")')
        lines.append(f'cmd.remove("solvent")')
        if code["chain"]:
            lines.append(f'cmd.remove("{code["pdb_id"]} and not chain {code["chain"]}")')
        lines.append(f'cmd.remove("all and not (resi {"+".join([str(i) for i in pocket_residues_ids])})")')
        lines.append(f'')

        # Set sphere color and size
        sphere_colors = {
            'ca': [0.0, 1.0, 0.0],  # Green
            'side_chain_centroid': [1.0, 0.0, 0.0],  # Red
            'pocket_centroid': [0.0, 0.0, 1.0],  # Blue
        }
        sphere_size = {
            'ca': str(0.2),
            'side_chain_centroid': str(0.2),
            'pocket_centroid': str(1)
        }

        # Collect all PyMol objects here (in order to group them after loading them to PyMol)
        obj_names = []
        obj_angle_names = []

        for index, row in self.features_verbose.iterrows():

            # Set PyMol object name: residue ID
            obj_name = f'{row.res_id}'
            obj_names.append(obj_name)

            if not np.isnan(row.sco):

                # Add angle to CA atom in the form of a label
                obj_angle_name = f'angle_{row.res_id}'
                obj_angle_names.append(obj_angle_name)

                lines.append(
                    f'cmd.pseudoatom(object="angle_{row.res_id}", '
                    f'pos=[{str(row.ca[0])}, {str(row.ca[1])}, {str(row.ca[2])}], '
                    f'label={str(round(row.sco, 1))})'
                )

            vectors = {
                'ca': row.ca,
                'side_chain_centroid': row.side_chain_centroid,
                'pocket_centroid': row.pocket_centroid
            }

            # Write all spheres for current residue in cgo format
            lines.append(f'obj_{obj_name} = [')  # Variable cannot start with digit, thus add prefix obj_

            # For each reference point, write sphere color, coordinates and size to file
            for key, vector in vectors.items():

                if vector:
                    # Set sphere color
                    sphere_color = list(sphere_colors[key])

                    # Write sphere a) color and b) coordinates and size to file
                    lines.extend(
                        [
                            f'\tCOLOR, {str(sphere_color[0])}, {str(sphere_color[1])}, {str(sphere_color[2])},',
                            f'\tSPHERE, {str(vector[0])}, {str(vector[1])}, {str(vector[2])}, {sphere_size[key]},'
                        ]
                    )

            # Load the spheres as PyMol object
            lines.extend(
                [
                    f']',
                    f'cmd.load_cgo(obj_{obj_name}, "{obj_name}")',
                    ''
                ]

            )
        # Group all objects to one group
        lines.append(f'cmd.group("{self.code.replace("/", "_")}", "{" ".join(obj_names + obj_angle_names)}")')

        cgo_path = Path(output_path) / f'side_chain_orientation_{self.code.split("/")[1]}.py'
        with open(cgo_path, 'w') as f:
            f.write('\n'.join(lines))

        # In PyMol enter the following to save png
        # PyMOL > ray 900, 900
        # PyMOL > save refpoints.png

    def show_in_nglviewer(self):

        # Get molecule and molecule code
        code = split_klifs_code(self.code)

        pdb_id = code['pdb_id']
        chain = code['chain']

        viewer = nv.show_pdbid(pdb_id, default=False)
        viewer.clear()
        viewer.add_cartoon(selection=f':{chain}', assembly='AU')
        viewer.center(selection=f':{chain}')

        # Representation parameters
        sphere_radius = {
            'ca': 0.3,
            'side_chain_centroid': 0.3,
            'pocket_centroid': 1
        }

        colors = {
            'ca': [0, 1, 0],
            'side_chain_centroid': [1, 0, 0],
            'pocket_centroid': [0, 0, 1]
        }

        # Show side chain angle feature per residue
        for index, row in self.features_verbose.iterrows():

            res_id = row.res_id

            viewer.add_representation(repr_type='line', selection=f'{res_id}:{chain}')
            viewer.add_label(selection=f'{res_id}:{chain}.CA')  # TODO: Add angles as label here

            if row.ca:
                ca = list(row.ca.get_array())
                viewer.shape.add_sphere(ca, colors['ca'], sphere_radius['ca'])

            if row.side_chain_centroid:
                side_chain_centroid = list(row.side_chain_centroid.get_array())
                viewer.shape.add_sphere(side_chain_centroid, colors['side_chain_centroid'], sphere_radius['side_chain_centroid'])

            if row.pocket_centroid:
                pocket_centroid = list(row.pocket_centroid.get_array())
                viewer.shape.add_sphere(pocket_centroid, colors['pocket_centroid'], sphere_radius['pocket_centroid'])

        viewer.gui_style = 'ngl'

        return viewer


class SideChainAngleFeature:
    """
    Side chain angles for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.
    Side chain angle of a residue is defined by the angle between the molecule's CB-CA and CB-centroid vectors.

    Attributes
    ----------
    features : pandas.DataFrame
        1 feature, i.e. side chain angle, (column) for 85 residues (rows).
    features_verbose : pandas.DataFrame
        Feature, Ca, Cb, and centroid vectors as well as metadata information (columns) for 85 residues (row).
    code : str
        KLIFS code.
    """

    def __init__(self):

        self.features = None
        self.features_verbose = None
        self.code = None

    def from_molecule(self, molecule, chain, fill_missing=False):
        """
        Get side chain angle for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        fill_missing : bool
            Fill missing values with median value of respective amino acid angle distribution.
        """

        self.code = molecule.code  # Necessary for cgo generation

        # Calculate/get CA, CB and centroid points
        ca_cb_com_vectors = self._get_ca_cb_com_vectors(molecule, chain)

        # Get angle values per residue
        side_chain_angles = self._get_side_chain_angles(ca_cb_com_vectors, fill_missing)

        # Store angles
        self.features = side_chain_angles
        # Store angles plus CA, CB and centroid points as well as metadata
        self.features_verbose = pd.concat([ca_cb_com_vectors, side_chain_angles], axis=1)

    @staticmethod
    def _get_side_chain_angles(ca_cb_com_vectors, fill_missing=False):
        """
        Calculate side chain angles for a molecule.

        Parameters
        ----------
        ca_cb_com_vectors : pandas.DataFrame
            CA, CB and centroid points for each residue of a molecule.
        fill_missing : bool
            Fill missing values with median value of respective amino acid angle distribution.

        Returns
        -------
        pandas.DataFrame
            1 feature, i.e. side chain angle, (column) for 85 residues (rows).
        """

        side_chain_angles = []

        for index, row in ca_cb_com_vectors.iterrows():

            # If residue is a GLY or ALA, set default angle of 180°
            if row.residue_name in ['GLY', 'ALA']:
                side_chain_angles.append(180.00)

            # If one of the other residues and all three Ca/Cb/centroid positions available, calculate centroid
            elif row.ca and row.cb and row.centroid:
                angle = np.degrees(calc_angle(row.ca, row.cb, row.centroid))
                side_chain_angles.append(angle.round(2))

            # If Ca, Cb, or centroid positions are missing for angle calculation...
            else:
                # ... set median value to residue
                if fill_missing:
                    angle = MEDIAN_SIDE_CHAIN_ANGLE[row.residue_name]

                # ... set None value to residue
                else:
                    angle = None
                side_chain_angles.append(angle)

        # Cast to DataFrame
        side_chain_angles = pd.DataFrame(
            side_chain_angles,
            index=ca_cb_com_vectors.klifs_id,
            columns=['sca']
        )

        return side_chain_angles

    def _get_ca_cb_com_vectors(self, molecule, chain):
        """
        Get CA, CB and centroid points for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.

        Returns
        -------
        pandas.DataFrame
            CA, CB and centroid points for each residue of a molecule.
        """

        # Get KLIFS residues in PDB file based on KLIFS mol2 file
        # Data type: list of Bio.PDB.Residue.Residue
        residues = Selection.unfold_entities(entity_list=chain, target_level='R')

        # Get KLIFS pocket residue IDs from mol2 file
        pocket_residue_ids = [int(i) for i in molecule.df.res_id.unique()]

        # Select KLIFS pocket residues
        pocket_residues = [residue for residue in residues if residue.get_full_id()[3][1] in pocket_residue_ids]

        # Save here values per residue
        data = []
        metadata = pd.DataFrame(
            list(molecule.df.groupby(by=['klifs_id', 'res_id', 'res_name'], sort=False).groups.keys()),
            index=molecule.df.klifs_id.unique(),
            columns='klifs_id residue_id residue_name'.split()
        )

        for residue in pocket_residues:

            vector_ca = self._get_ca(residue)
            vector_cb = self._get_cb(residue)
            vector_centroid = self._get_side_chain_centroid(residue)

            data.append([vector_ca, vector_cb, vector_centroid])

        data = pd.DataFrame(
            data,
            index=molecule.df.klifs_id.unique(),
            columns='ca cb centroid'.split()
        )

        if len(metadata) != len(data):
            raise ValueError(f'DataFrames to be concatenated must be of same length: '
                             f'Metadata has {len(metadata)} rows, CA/CB/centroid data has {len(data)} rows.')

        return pd.concat([metadata, data], axis=1)

    @staticmethod
    def _get_ca(residue):
        """
        Get residue's Ca atom.

        Parameters
        ----------
        residue : Bio.PDB.Residue.Residue
            Residue.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's Ca vector.
        """

        atom_names = [atoms.fullname for atoms in residue.get_atoms()]

        # Set CA atom
        if 'CA' in atom_names:
            vector_ca = residue['CA'].get_vector()
        else:
            vector_ca = None

        return vector_ca

    @staticmethod
    def _get_cb(residue):
        """
        Get residue's Cb atom.

        Parameters
        ----------
        residue : Bio.PDB.Residue.Residue
            Residue.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's Cb vector.
        """

        atom_names = [atoms.fullname for atoms in residue.get_atoms()]

        if 'CB' in atom_names:
            vector_cb = residue['CB'].get_vector()
        else:
            vector_cb = None

        return vector_cb

    @staticmethod
    def _get_side_chain_centroid(residue):
        """
        Get residue's side chain centroid.

        Parameters
        ----------
        residue : Bio.PDB.Residue.Residue
            Residue.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's side chain centroid.
        """

        # Select only atoms that are
        # - not part of the backbone
        # - not oxygen atoms (OXT) on the terminal carboxyl group
        # - not H atoms

        selected_atoms = [
            atom for atom in residue.get_atoms() if
            (atom.fullname not in 'N CA C O OXT'.split()) & (not atom.get_id().startswith('H'))
        ]

        if len(selected_atoms) <= 1:  # Too few side chain atoms for centroid calculation
            return None

        try:  # If standard residue, calculate centroid only if enough side chain atoms available
            if len(selected_atoms) < N_HEAVY_ATOMS_CUTOFF[residue.get_resname()]:
                return None
            else:
                return Vector(center_of_mass(selected_atoms, geometric=True))

        except KeyError:  # If non-standard residue, use whatever side chain atoms available
            return Vector(center_of_mass(selected_atoms, geometric=True))

    def save_cgo_side_chain_angle(self, output_path):
        """
        Save Ca, Cb, and centroid as spheres and label Cb with side chain angle value to PyMol cgo file.

        Parameters
        ----------
        output_path : pathlib.Path or str
            Path to output directory.
        """

        # Get molecule and molecule code
        code = split_klifs_code(self.code)

        # Get pocket residues
        pocket_residues_ids = list(self.features_verbose.residue_id)

        # List contains lines for python script
        lines = [f'from pymol import *', f'import os', f'from pymol.cgo import *\n']

        # Fetch PDB, remove solvent, remove unnecessary chain(s) and residues
        lines.append(f'cmd.fetch("{code["pdb_id"]}")')
        lines.append(f'cmd.remove("solvent")')
        if code["chain"]:
            lines.append(f'cmd.remove("{code["pdb_id"]} and not chain {code["chain"]}")')
        lines.append(f'cmd.remove("all and not (resi {"+".join([str(i) for i in pocket_residues_ids])})")')
        lines.append(f'')

        # Set sphere color and size
        sphere_colors = {
            'ca': [1.0, 0.0, 0.0],  # red
            'cb': [0.0, 1.0, 1.0],  # green
            'centroid': [0.0, 0.0, 1.0],  # blue
        }
        sphere_size = str(0.2)

        # Collect all PyMol objects here (in order to group them after loading them to PyMol)
        obj_names = []
        obj_angle_names = []

        for index, row in self.features_verbose.iterrows():

            # Set PyMol object name: residue ID
            obj_name = f'{row.residue_id}'
            obj_names.append(obj_name)

            if row.cb:

                # Add angle to CB atom in the form of a label
                obj_angle_name = f'angle_{row.residue_id}'
                obj_angle_names.append(obj_angle_name)

                lines.append(
                    f'cmd.pseudoatom(object="angle_{row.residue_id}", '
                    f'pos=[{str(row.cb[0])}, {str(row.cb[1])}, {str(row.cb[2])}], '
                    f'label={str(round(row.sca, 1))})'
                )

            vectors = {
                'ca': row.ca,
                'cb': row.cb,
                'centroid': row.centroid
            }

            # Write all spheres for current residue in cgo format
            lines.append(f'obj_{obj_name} = [')  # Variable cannot start with digit, thus add prefix obj_

            # For each reference point, write sphere color, coordinates and size to file
            for key, vector in vectors.items():

                if vector:
                    # Set sphere color
                    sphere_color = list(sphere_colors[key])

                    # Write sphere a) color and b) coordinates and size to file
                    lines.extend(
                        [
                            f'\tCOLOR, {str(sphere_color[0])}, {str(sphere_color[1])}, {str(sphere_color[2])},',
                            f'\tSPHERE, {str(vector[0])}, {str(vector[1])}, {str(vector[2])}, {sphere_size},'
                        ]
                    )

            # Load the spheres as PyMol object
            lines.extend(
                [
                    f']',
                    f'cmd.load_cgo(obj_{obj_name}, "{obj_name}")',
                    ''
                ]

            )
        # Group all objects to one group
        lines.append(f'cmd.group("{self.code.replace("/", "_")}", "{" ".join(obj_names + obj_angle_names)}")')

        cgo_path = Path(output_path) / f'side_chain_angle_{self.code.split("/")[1]}.py'
        with open(cgo_path, 'w') as f:
            f.write('\n'.join(lines))


class ExposureFeature:
    """
    Exposure for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.
    Exposure of a residue describes the ratio of CA atoms in the upper sphere half around the CA-CB vector
    divided by the all CA atoms (given a sphere radius).

    Attributes
    ----------
    features : pandas.DataFrame
        1 features (columns) for 85 residues (rows).
    """

    def __init__(self):

        self.features = None

    def from_molecule(self, molecule, chain, verbose=False):
        """
        Get exposure for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        verbose : bool
            Either return exposure only (default) or additional info on HSExposureCA and HSExposureCB values.
        """

        # Calculate exposure values
        exposures_cb = self.get_exposure_by_method(chain, method='HSExposureCB')
        exposures_ca = self.get_exposure_by_method(chain, method='HSExposureCA')

        # Join both exposures calculations
        exposures_both = exposures_ca.join(exposures_cb, how='outer')

        # Get residues IDs belonging to KLIFS binding site
        klifs_res_ids = molecule.df.groupby(by=['res_id', 'klifs_id'], sort=False).groups.keys()
        klifs_res_ids = pd.DataFrame(klifs_res_ids, columns=['res_id', 'klifs_id'])
        klifs_res_ids.set_index('res_id', inplace=True, drop=False)

        # Keep only KLIFS residues
        # i.e. remove non-KLIFS residues and add KLIFS residues that were skipped in exposure calculation
        exposures = klifs_res_ids.join(exposures_both, how='left')

        # Set index (from residue IDs) to KLIFS IDs
        exposures.set_index('klifs_id', inplace=True, drop=True)

        # Add column with CB exposure values AND CA exposure values if CB exposure values are missing
        exposures['exposure'] = exposures.apply(
            lambda row: row.ca_exposure if np.isnan(row.cb_exposure) else row.cb_exposure,
            axis=1
        )

        if not verbose:
            self.features = pd.DataFrame(
                exposures.exposure,
                index=exposures.exposure.index,
                columns=['exposure']
            )
        else:
            self.features = exposures

    @staticmethod
    def get_exposure_by_method(chain, method='HSExposureCB'):
        """
        Get exposure values for a given Half Sphere Exposure method, i.e. HSExposureCA or HSExposureCB.

        Parameters
        ----------
        chain : Bio.PDB.Chain.Chain
            Chain from PDB file.
        method : str
            Half sphere exposure method name: HSExposureCA or HSExposureCB.

        References
        ----------
        Read on HSExposure module here: https://biopython.org/DIST/docs/api/Bio.PDB.HSExposure-pysrc.html
        """

        methods = 'HSExposureCB HSExposureCA'.split()

        # Calculate exposure values
        if method == methods[0]:
            exposures = HSExposureCB(chain, EXPOSURE_RADIUS)
        elif method == methods[1]:
            exposures = HSExposureCA(chain, EXPOSURE_RADIUS)
        else:
            raise ValueError(f'Method {method} unknown. Please choose from: {", ".join(methods)}')

        # Define column names
        up = f'{method[-2:].lower()}_up'
        down = f'{method[-2:].lower()}_down'
        angle = f'{method[-2:].lower()}_angle_Ca-Cb_Ca-pCb'
        exposure = f'{method[-2:].lower()}_exposure'

        # Transform into DataFrame
        exposures = pd.DataFrame(
            exposures.property_dict,
            index=[up, down, angle]
        ).transpose()
        exposures.index = [i[1][1] for i in exposures.index]

        # Check that exposures are floats (important for subsequent division)
        if (exposures[up].dtype != 'float64') | (exposures[down].dtype != 'float64'):
            raise TypeError(f'Wrong dtype, float64 needed!')

        # Calculate exposure value: up / (up + down)
        exposures[exposure] = exposures[up] / (exposures[up] + exposures[down])

        return exposures


class PharmacophoreSizeFeatures:
    """
    Pharmacophore and size features for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned
    residues, as described by SiteAlign (Schalon et al. Proteins. 2008).

    Pharmacophoric features include hydrogen bond donor, hydrogen bond acceptor, aromatic, aliphatic and charge feature.

    Attributes
    ----------
    features : pandas.DataFrame
        6 features (columns) for 85 residues (rows).

    References
    ----------
    Schalon et al., "A simple and fuzzy method to align and compare druggable ligand‐binding sites",
    Proteins, 2008.
    """

    def __init__(self):

        self.features = None

    def from_molecule(self, molecule):
        """
        Get pharmacophoric and size features for each residues of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.

        Returns
        -------
        pandas.DataFrame
            Pharmacophoric and size features (columns) for each residue = KLIFS position (rows).
        """

        feature_types = 'size hbd hba charge aromatic aliphatic'.split()

        feature_matrix = []

        for feature_type in feature_types:

            # Select from DataFrame first row per KLIFS position (index) and residue name
            residues = molecule.df.groupby(by='klifs_id', sort=False).first()['res_name']

            # Report non-standard residues in molecule
            non_standard_residues = set(residues) - set(STANDARD_AA)
            if len(non_standard_residues) > 0:
                logger.info(f'Non-standard amino acid in {molecule.code}: {non_standard_residues}')

            features = residues.apply(lambda residue: self.from_residue(residue, feature_type))
            features.rename(feature_type, inplace=True)

            feature_matrix.append(features)

        features = pd.concat(feature_matrix, axis=1)

        self.features = features

    @staticmethod
    def from_residue(residue, feature_type):
        """
        Get feature value for residue's size and pharmacophoric features (i.e. number of hydrogen bond donor,
        hydrogen bond acceptors, charge features, aromatic features or aliphatic features)
        (according to SiteAlign feature encoding).

        Parameters
        ----------
        residue : str
            Three-letter code for residue.
        feature_type : str
            Feature type name.

        Returns
        -------
        int
            Residue's size value according to SiteAlign feature encoding.
        """

        if feature_type not in FEATURE_LOOKUP.keys():
            raise KeyError(f'Feature {feature_type} does not exist. '
                           f'Please choose from: {", ".join(FEATURE_LOOKUP.keys())}')

        # Manual addition of modified residue(s)
        if residue in MODIFIED_AA_CONVERSION.keys():
            residue = MODIFIED_AA_CONVERSION[residue]

        # Start with a feature of None
        result = None

        # If residue name is listed in the feature lookup, assign respective feature
        for feature, residues in FEATURE_LOOKUP[feature_type].items():

            if residue in residues:
                result = feature

        return result


########################################################################################################################
# Not in use
########################################################################################################################

class SideChainAngleFeatureMol2:
    """
    Side chain angles for each residue in the KLIFS-defined kinase binding site of 85 pre-aligned residues.
    Side chain angle of a residue is defined by the angle between the molecule's CB-CA and CB-centroid vectors.

    Attributes
    ----------
    features : pandas.DataFrame
        1 feature, i.e. side chain angle, (column) for 85 residues (rows).
    features_verbose : pandas.DataFrame
        Feature, Ca, Cb, and centroid vectors as well as metadata information (columns) for 85 residues (row).
    code : str
        KLIFS code.
    """

    def __init__(self):

        self.features = None
        self.features_verbose = None
        self.code = None

    def from_molecule(self, molecule, fill_missing=False):
        """
        Get side chain angle for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.
        fill_missing : bool
            Fill missing values with median value of respective amino acid angle distribution.
        """

        self.code = molecule.code  # Necessary for cgo generation

        # Calculate/get CA, CB and centroid points
        ca_cb_com_vectors = self._get_ca_cb_com_vectors(molecule)

        # Get angle values per residue
        side_chain_angles = self._get_side_chain_angles(ca_cb_com_vectors, fill_missing)

        # Store angles
        self.features = side_chain_angles
        # Store angles plus CA, CB and centroid points as well as metadata
        self.features_verbose = pd.concat([ca_cb_com_vectors, side_chain_angles], axis=1)

    @staticmethod
    def _get_side_chain_angles(ca_cb_com_vectors, fill_missing=False):
        """
        Calculate side chain angles for a molecule.

        Parameters
        ----------
        ca_cb_com_vectors : pandas.DataFrame
            CA, CB and centroid points for each residue of a molecule.
        fill_missing : bool
            Fill missing values with median value of respective amino acid angle distribution.

        Returns
        -------
        pandas.DataFrame
            1 feature, i.e. side chain angle, (column) for 85 residues (rows).
        """

        side_chain_angles = []

        for index, row in ca_cb_com_vectors.iterrows():

            # If residue is a GLY or ALA, set default angle of 180°
            if row.residue_name in ['GLY', 'ALA']:
                side_chain_angles.append(180.00)

            # If one of the other residues and all three Ca/Cb/centroid positions available, calculate centroid
            elif row.ca and row.cb and row.centroid:
                angle = np.degrees(calc_angle(row.ca, row.cb, row.centroid))
                side_chain_angles.append(angle.round(2))

            # If Ca, Cb, or centroid positions are missing for angle calculation...
            else:
                # ... set median value to residue
                if fill_missing:
                    angle = MEDIAN_SIDE_CHAIN_ANGLE[row.residue_name]

                # ... set None value to residue
                else:
                    angle = None
                side_chain_angles.append(angle)

        # Cast to DataFrame
        side_chain_angles = pd.DataFrame(
            side_chain_angles,
            index=ca_cb_com_vectors.klifs_id,
            columns=['sca']
        )

        return side_chain_angles

    def _get_ca_cb_com_vectors(self, molecule):
        """
        Get CA, CB and centroid points for each residue of a molecule.

        Parameters
        ----------
        molecule : biopandas.mol2.pandas_mol2.PandasMol2 or biopandas.pdb.pandas_pdb.PandasPdb
            Content of mol2 or pdb file as BioPandas object.

        Returns
        -------
        pandas.DataFrame
            CA, CB and centroid points for each residue of a molecule.
        """

        # Save here values per residue
        data = []
        metadata = pd.DataFrame(
            list(molecule.df.groupby(by=['klifs_id', 'res_id', 'res_name'], sort=False).groups.keys()),
            index=molecule.df.klifs_id.unique(),
            columns='klifs_id residue_id residue_name'.split()
        )

        for residue_id, residue in molecule.df.groupby('res_id'):
            vector_ca = self._get_ca(residue)
            vector_cb = self._get_cb(residue)
            vector_centroid = self._get_side_chain_centroid(residue)

            data.append([vector_ca, vector_cb, vector_centroid])

        data = pd.DataFrame(
            data,
            index=molecule.df.klifs_id.unique(),
            columns='ca cb centroid'.split()
        )

        if len(metadata) != len(data):
            raise ValueError(f'DataFrames to be concatenated must be of same length: '
                             f'Metadata has {len(metadata)} rows, CA/CB/centroid data has {len(data)} rows.')

        return pd.concat([metadata, data], axis=1)

    @staticmethod
    def _get_ca(residue):
        """
        Get residue's Ca atom.

        Parameters
        ----------
        residue : pandas.DataFrame
            Residue's atoms.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's Ca vector.
        """

        ca = residue[residue.atom_name == 'CA']

        if len(ca) == 1:
            return Vector(ca['x y z'.split()].values[0])
        elif len(ca) == 0:
            return None
        else:
            raise ValueError(f'Residue has more than one, i.e. {len(ca)}, CA atoms.')

    @staticmethod
    def _get_cb(residue):
        """
        Get residue's Cb atom.

        Parameters
        ----------
        residue : pandas.DataFrame
            Residue's atoms.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's Cb vector.
        """

        cb = residue[residue.atom_name == 'CB']

        if len(cb) == 1:
            return Vector(cb['x y z'.split()].values[0])
        elif len(cb) == 0:
            return None
        else:
            raise ValueError(f'Residue has more than one, i.e. {len(cb)}, CB atoms.')

    @staticmethod
    def _get_side_chain_centroid(residue):
        """
        Get residue's side chain centroid.

        Parameters
        ----------
        residue : pandas.DataFrame
            Residue's atoms.

        Returns
        -------
        Bio.PDB.vectors.Vector
            Residue's side chain centroid.
        """

        # Select only atoms that are
        # - not part of the backbone
        # - not oxygen atoms (OXT) on the terminal carboxyl group
        # - not H atoms

        selected_atoms = residue[
            (~residue.atom_name.isin(['N', 'C', 'O', 'CA', 'OXT'])) & (~residue.atom_name.str.startswith('H'))
        ]

        if len(selected_atoms) <= 1:  # Too few side chain atoms for centroid calculation
            return None

        try:  # If standard residue, calculate centroid only if enough side chain atoms available
            if len(selected_atoms) < N_HEAVY_ATOMS_CUTOFF[residue.res_name.unique()[0]]:
                return None
            else:
                return Vector(list(selected_atoms['x y z'.split()].mean()))

        except KeyError:  # If non-standard residue, use whatever side chain atoms available
            return Vector(list(selected_atoms['x y z'.split()].mean()))