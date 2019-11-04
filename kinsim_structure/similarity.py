"""
similarity.py

Subpocket-based structural fingerprint for kinase pocket comparison.

Handles the primary functions for the structural kinase fingerprint comparison.
"""

import logging

import numpy as np
import pandas as pd
from scipy.spatial import distance

from kinsim_structure.encoding import FEATURE_NAMES

logger = logging.getLogger(__name__)

FEATURE_DISTANCES_FORMAT = {
    'physicochemical': [None]*8,
    'distances': [None]*4,
    'moments': [None]*3
}


class FeatureDistances:
    """
    Distances between two fingerprints for each of their features, including information on feature bit coverage and
    bit number, in order to assess how reliable the feature distance is.

    Attributes
    ----------
    molecule_codes : list of str
        Codes of both molecules represented by the fingerprints.
    data : pandas.DataFrame
        Distances between two fingerprints for each of their features, plus details on feature type, feature,
        feature bit coverage, and feature bit number.
    """

    def __init__(self):

        self.molecule_codes = None
        self.data = None

    def from_fingerprints(self, fingerprint1, fingerprint2, distance_measure='euclidean'):
        """
        Calculate distance between two fingerprints for each feature.

        Parameters
        ----------
        fingerprint1 : encoding.Fingerprint
            Fingerprint 1.
        fingerprint2 : encoding.Fingerprint
            Fingerprint 2.
        distance_measure : str
            Type of distance measure.

        Returns
        -------
        pandas.DataFrame
            Distances between two fingerprints for each of their features, plus details on feature type, feature,
            feature bit coverage, and feature bit number.
        """

        self.molecule_codes = [fingerprint1.molecule_code, fingerprint2.molecule_code]

        # Get fingerprint pair (normalized fingerprints only)
        fingerprint_pair = self._extract_fingerprint_pair(fingerprint1, fingerprint2, normalized=True)

        distances = []

        for feature_type in FEATURE_NAMES.keys():

            for feature_name in FEATURE_NAMES[feature_type]:

                # Get feature distance
                distance = self._calc_feature_distance(
                        fingerprint_pair[feature_type][feature_name],
                        distance_measure
                    )

                # Get number of feature bits without any NaN value
                bit_number = len(fingerprint_pair[feature_type][feature_name])

                # Get bit coverage
                bit_coverage = self._get_bit_coverage(feature_type, bit_number)

                # Save feature data to fingerprint data
                distances.append([feature_type, feature_name, distance, bit_coverage, bit_number])

        self.data = pd.DataFrame(
            distances,
            columns='feature_type feature_name distance bit_coverage bit_number'.split()
        )

    @staticmethod
    def _get_bit_coverage(feature_type, bit_number):
        """
        Get bit coverage for a given feature type.

        Parameters
        ----------
        feature_type : str
            Feature type: physicochemical, distances or moments.
        bit_number : int
            Number of feature bits used for distance calculation.

        Returns
        -------
        float
            Bit coverage describing the percentage of bits used for distance calculation.
        """

        if feature_type not in FEATURE_NAMES.keys():
            raise ValueError(f'Feature type unknown. Choose from: {", ".join(list(FEATURE_NAMES.keys()))}.')

        bit_number_moments = 4.0
        bit_number_other = 85.0

        if feature_type is 'moments':

            if 0 <= bit_number <= bit_number_moments:
                return round(bit_number / bit_number_moments, 2)
            else:
                raise ValueError(f'Unexcepted number of bits for {feature_type}: '
                                 f'Is {bit_number}, but must be between 0 and {int(bit_number_moments)}.')

        else:

            if 0 <= bit_number <= bit_number_other:
                return round(bit_number / bit_number_other, 2)
            else:
                raise ValueError(f'Unexcepted number of bits for {feature_type}: '
                                 f'Is {bit_number}, but must be between 0 and {int(bit_number_other)}.')

    def _calc_feature_distance(self, feature_pair, distance_measure='euclidean'):
        """
        Calculate distance between two value lists (describing each the same feature).

        Parameters
        ----------
        feature_pair : pandas.DataFrame
            Pairwise bits of one feature extracted from two fingerprints (only bit positions without any NaN value).
        distance_measure : str
            Distance measure.

        Returns
        -------
        dict
            Distance between two value lists (describing each the same feature).
        """

        distance_measures = 'euclidean'.split()

        if not isinstance(distance_measure, str):
            raise TypeError(f'Parameter "distance_measure" must be of type str, but is {type(distance_measure)}.')

        if distance_measure not in distance_measures:
            raise ValueError(f'Distance measure unknown. Choose from: {", ".join(distance_measures)}')

        if not isinstance(feature_pair, pd.DataFrame):
            raise TypeError(f'Parameter "feature_pair" must be of type pandas.DataFrame, but is {type(feature_pair)}.')

        if feature_pair.shape[1] != 2:
            raise ValueError(f'Parameter "feature_pair" must be pandas.DataFrame with two columns, '
                             f'but has {feature_pair.shape[1]} columns.')

        # Set feature distance to NaN if no bits available for distance calculation
        if len(feature_pair) == 0:
            return np.nan

        # In case there are still NaN positions, remove bit positions containing any NaN value
        feature_pair.dropna(how='any', axis=0, inplace=True)

        # Get feature distance
        if distance_measure == 'euclidean':
            return self._euclidean_distance(
                feature_pair.iloc[:, 0],  # Fingerprint 1
                feature_pair.iloc[:, 1]  # Fingerprint 2
            )

        else:
            raise ValueError(f'Distance measure unknown. Choose from: {", ".join(distance_measures)}')

    @staticmethod
    def _extract_fingerprint_pair(fingerprint1, fingerprint2, normalized=True):
        """
        For each feature, get both fingerprint bits without NaN positions.

        Parameters
        ----------
        fingerprint1 : encoding.Fingerprint
            Fingerprint 1.
        fingerprint2 : encoding.Fingerprint
            Fingerprint 2.
        normalized : bool
            Normalized (default) or non-normalized fingerprints.

        Returns
        -------
        dict of dict of pandas.DataFrame
            For each feature type, i.e. physicochemical, distances, and moments (dict) and for each corresponding
            feature, i.e. size, HBD, HDA, ... for physicochemical feature type (dict), non-NaN bits from both
            fingerprints (pandas.DataFrame).
        """

        if normalized:
            f1 = fingerprint1.fingerprint_normalized
            f2 = fingerprint2.fingerprint_normalized
        else:
            f1 = fingerprint1.fingerprint
            f2 = fingerprint2.fingerprint

        fingerprint_pair = {}

        # Iterate over all feature types
        for feature_type in FEATURE_NAMES.keys():

            fingerprint_pair[feature_type] = {}

            # Iterate over all features
            for feature_name in FEATURE_NAMES[feature_type]:

                # Concatenate feature bits from both fingerprints and remove bits where one or both bits are NaN
                feature_pair = pd.concat(
                    [f1[feature_type][feature_name], f2[feature_type][feature_name]],
                    axis=1
                )
                feature_pair.columns = ['fingerprint1', 'fingerprint2']
                feature_pair.dropna(how='any', axis=0, inplace=True)

                fingerprint_pair[feature_type][feature_name] = feature_pair

        return fingerprint_pair

    @staticmethod
    def _euclidean_distance(values1, values2):
        """
        Calculate Euclidean distance between two value lists of same length.

        Parameters
        ----------
        values1 : list or pandas.Series
            Value list (same length as values2).
        values2 : list or pandas.Series
            Value list (same length as values1).

        Returns
        -------
        float
            Euclidean distance between two value lists.
        """

        if len(values1) != len(values2):
            raise ValueError(f'Distance calculation failed: Values lists are not of same length.')
        elif len(values1) == 0:
            return np.nan
        else:
            d = 1 / len(values1) * distance.euclidean(values1, values2)
            return d

    @staticmethod
    def _cityblock_distance(values1, values2):
        """
        Calculate cityblock distance between two value lists of same length.

        Parameters
        ----------
        values1 : list or pandas.Series
            Value list (same length as values2).
        values2 : list or pandas.Series
            Value list (same length as values1).

        Returns
        -------
        float
            Euclidean distance between two value lists.
        """

        if len(values1) != len(values2):
            raise ValueError(f'Distance calculation failed: Values lists are not of same length.')
        elif len(values1) == 0:
            return np.nan
        else:
            d = 1 / len(values1) * distance.cityblock(values1, values2)
            return d
