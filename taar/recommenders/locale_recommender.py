import logging
import json
from collections import defaultdict
from ..recommenders import utils
from .base_recommender import BaseRecommender

ADDON_LIST_BUCKET = 'telemetry-parquet'
ADDON_LIST_KEY = 'taar/locale/top10_dict.json'


logger = logging.getLogger(__name__)


class LocaleRecommender(BaseRecommender):
    """ A recommender class that returns top N addons based on the client geo-locale.

    This will load a json file containing updated top n addons in use per geo locale
    updated periodically by a separate process on airflow using Longitdudinal Telemetry
    data.

    This recommender may provide useful recommendations when collaborative_recommender
    may not work.
    """
    def __init__(self, TOP_ADDONS_BY_LOCALE_FILE_PATH):
        self.top_addons_per_locale = utils.get_s3_json_content(ADDON_LIST_BUCKET,
                                                               ADDON_LIST_KEY)
        if self.top_addons_per_locale is None:
            logger.error("Cannot download the top per locale file {}".format(ADDON_LIST_KEY))

        with open(TOP_ADDONS_BY_LOCALE_FILE_PATH) as data_file:
            top_addons_by_locale = json.load(data_file)

        self.top_addons_by_locale = defaultdict(lambda: defaultdict(int), top_addons_by_locale)

    def can_recommend(self, client_data):
        # We can't recommend if we don't have our data files.
        if self.top_addons_per_locale is None:
            return False
        client_locale = client_data.get('locale', None)
        if not isinstance(client_locale, str):
            return False

        if client_locale not in self.top_addons_per_locale:
            return False

        if not self.top_addons_per_locale.get(client_locale):
            return False

        return True

    def recommend(self, client_data, limit):
        client_locale = client_data.get('locale')
        return self.top_addons_per_locale.get(client_locale, [])[:limit]

    def get_weighted_recommendations(self, client_data):
        client_locale = client_data.get('locale', None)
        return defaultdict(int, self.top_addons_by_locale[client_locale])
