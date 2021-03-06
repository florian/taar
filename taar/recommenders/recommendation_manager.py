import logging
from .collaborative_recommender import CollaborativeRecommender
from .legacy_recommender import LegacyRecommender
from .locale_recommender import LocaleRecommender
from .similarity_recommender import SimilarityRecommender
from ..profile_fetcher import ProfileFetcher


logger = logging.getLogger(__name__)


class RecommendationManager(object):
    """A class representing a collection of recommenders."""

    def __init__(self, profile_fetcher=None, recommenders=None):
        """Initialize the user profile fetcher and the recommenders.

        Note: The order of the recommenders matters!
        """
        if profile_fetcher is None:
            logger.info("Initializing profile_fetcher")
            self.profile_fetcher = ProfileFetcher()
        else:
            self.profile_fetcher = profile_fetcher

        if not recommenders:
            logger.info("Initializing recommenders")
            self.recommenders = (
                LegacyRecommender(),
                CollaborativeRecommender(),
                SimilarityRecommender(),
                LocaleRecommender()
            )
        else:
            self.recommenders = recommenders

    def recommend(self, client_id, limit):
        """Return recommendations for the given client.

        The recommendation logic will go through each recommender and pick the
        first one that "can_recommend".
        """
        # Get the info for the requested client id.
        client_info = self.profile_fetcher.get(client_id)
        if client_info is None:
            return []

        # Compute the recommendation.
        for r in self.recommenders:
            if r.can_recommend(client_info):
                logger.info("Recommender selected", extra={
                    "client_id": client_id, "recommender": str(r)
                })
                recommendations = r.recommend(client_info, limit)
                if not recommendations:
                    logger.info("No recommendations", extra={
                        "client_id": client_id, "recommender": str(r)
                    })

                return recommendations
        logger.info("No recommender can recommend addons", extra={
            "client_id": client_id
        })
        return []
