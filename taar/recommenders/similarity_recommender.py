import logging
import numpy as np
from ..recommenders import utils
from .base_recommender import BaseRecommender
from scipy.spatial import distance

CATEGORICAL_FEATURES = ["geo_city", "locale", "os"]
CONTINUOUS_FEATURES = ["subsession_length", "bookmark_count", "tab_open_count", "total_uri", "unique_tlds"]

S3_BUCKET = 'telemetry-parquet'
DONOR_LIST_KEY = 'taar/similarity/donors.json'
LR_CURVES_SIMILARITY_TO_PROBABILITY = 'taar/similarity/lr_curves.json'

logger = logging.getLogger(__name__)


class SimilarityRecommender(BaseRecommender):
    """ A recommender class that returns top N addons based on the client similarity
    with a set of candidate addon donors. Several telemetry fields are used to compute
    pairwise similarity with the donors and similarities are converted into a likelihood
    ratio of being a good match versus not being a good match. These quantities are then
    used to rank specific addons for recommendation.

    This will load a json file containing updated list of addon donors updated periodically
    by a separate weekly process using Longitdudinal Telemetry data.

    This recommender may provide useful recommendations when collaborative_recommender
    may not work.
    """

    def __init__(self):
        # Download the addon donors list.
        self.donors_pool = utils.get_s3_json_content(S3_BUCKET, DONOR_LIST_KEY)
        if self.donors_pool is None:
            logger.error("Cannot download the donor list: {}".format(DONOR_LIST_KEY))

        # Download the probability mapping curves from similarity to likelihood of being a good donor.
        self.lr_curves = utils.get_s3_json_content(S3_BUCKET, LR_CURVES_SIMILARITY_TO_PROBABILITY)
        if self.lr_curves is None:
            logger.error("Cannot download the lr curves: {}".format(LR_CURVES_SIMILARITY_TO_PROBABILITY))

        self.build_features_caches()

    def build_features_caches(self):
        """This function build two feature cache matrices.

        One matrix is for the continuous features and the other is for
        the categorical features. This is needed to speed up the similarity
        recommendation process."""
        if self.donors_pool is None or self.lr_curves is None:
            return None

        self.num_donors = len(self.donors_pool)

        # Build a numpy matrix cache for the continuous features.
        self.continuous_features = np.zeros((self.num_donors, len(CONTINUOUS_FEATURES)))
        for idx, d in enumerate(self.donors_pool):
            features = [d.get(specified_key) for specified_key in CONTINUOUS_FEATURES]
            self.continuous_features[idx] = features

        # Build the cache for categorical features.
        self.categorical_features =\
            np.zeros((self.num_donors, len(CATEGORICAL_FEATURES)), dtype='object')
        for idx, d in enumerate(self.donors_pool):
            features = [d.get(specified_key) for specified_key in CATEGORICAL_FEATURES]
            self.categorical_features[idx] = np.array([features], dtype="object")

        # This will significantly speed up |get_lr|.
        self.lr_curves_cache = np.array([s[0] for s in self.lr_curves])

    def can_recommend(self, client_data):
        # We can't recommend if we don't have our data files.
        if self.donors_pool is None or self.lr_curves is None:
            return False

        # Check that the client info contains a non-None value for each required
        # telemetry field.
        REQUIRED_FIELDS = CATEGORICAL_FEATURES + CONTINUOUS_FEATURES

        has_fields = all([client_data.get(f, None) is not None for f in REQUIRED_FIELDS])
        if not has_fields:
            # Can not add extra info because client_id may not be available.
            logger.error("Unusable client data encountered")
        return has_fields

    def get_lr(self, score):
        """Compute a :float: likelihood ratio from a provided similarity score when compared
        to two probability density functions which are computed and pre-loaded during init.

        The numerator indicates the probability density that a particular similarity score
        corresponds to a 'good' addon donor, i.e. a client that is similar in the sense of
        telemetry variables. The denominator indicates the probability density that a particular
        similarity score corresponds to a 'poor' addon donor

        :param score: A similarity score between a pair of objects.
        :returns: The approximate float likelihood ratio corresponding to provided score.
        """
        # Find the index of the closest value that was precomputed in lr_curves
        idx = np.argmin(abs(score - self.lr_curves_cache))

        numer_val = self.lr_curves[idx][1][0]
        denum_val = self.lr_curves[idx][1][1]

        # Compute LR based on numerator and denominator values
        return float(numer_val) / float(denum_val)

    def get_similar_donors(self, client_data):
        """Computes a set of :float: similarity scores between a client and a set of candidate
        donors for which comparable variables have been measured.

        A custom similarity metric is defined in this function that combines the Hamming distance
        for categorical variables with the Canberra distance for continuous variables into a
        univariate similarity metric between the client and a set of candidate donors loaded during
        init.

        :param client_data: a client data payload including a subset fo telemetry fields.
        :return: the sorted approximate likelihood ratio (np.array) corresponding to the
                 internally computed similarity score and a list of indices that link
                 each LR score with the related donor in the |self.donors_pool|.
        """
        client_categorical_feats = [client_data.get(specified_key) for specified_key in CATEGORICAL_FEATURES]
        client_continuous_feats = [client_data.get(specified_key) for specified_key in CONTINUOUS_FEATURES]

        # Compute the distances between the user and the cached continuous
        # and categorical features.
        cont_features = distance.cdist(self.continuous_features,
                                       np.array([client_continuous_feats]),
                                       'canberra')
        # The lambda trick is needed to prevent |cdist| from force-casting the
        # string features to double.
        cat_features = distance.cdist(self.categorical_features,
                                      np.array([client_categorical_feats]),
                                      lambda x, y: distance.hamming(x, y))

        # Take the product of similarities to attain a univariate similarity score.
        # Addition of 0.001 to the continuous features avoids a zero value from the
        # categorical variables, allowing categorical features precedence.
        distances = (cont_features + 0.001) * cat_features

        # Compute the LR based on precomputed distributions that relate the score
        # to a probability of providing good addon recommendations.
        lrs_from_scores =\
            np.array([self.get_lr(distances[i]) for i in range(self.num_donors)])

        # Sort the LR values (descending) and return the sorted values together with
        # the original indices.
        indices = (-lrs_from_scores).argsort()
        return lrs_from_scores[indices], indices

    def recommend(self, client_data, limit=10):
        donor_set_ranking, indices = self.get_similar_donors(client_data)
        # 2.0 corresponds to a likelihood ratio of 2 meaning that donors are less than twice
        # as likely to be 'good'. A value > 1.0 is sufficient, but we like this to be high.
        if donor_set_ranking[0] < 2.0:
            logger.warning("Addons recommended with very low similarity score, perhaps donor set is unrepresentative",
                           extra={"maximum_similarity": donor_set_ranking[0]})

        # Retrieve the indices of the highest ranked donors and then append their
        # installed addons.
        highest_scores_indices = indices[donor_set_ranking > 1.0]

        recommendations = []
        for good_candidate_index in highest_scores_indices:
            recommendations.extend(self.donors_pool[good_candidate_index]['active_addons'])
            if len(recommendations) > limit:
                break
        return recommendations[:limit]
