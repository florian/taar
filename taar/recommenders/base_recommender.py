from abc import ABCMeta, abstractmethod


class BaseRecommender:
    """Base class for recommenders.

    Subclasses must implement can_recommend and recommend.
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def can_recommend(self, client_data):
        """Tell whether this recommender can recommend the given client."""
        pass

    @abstractmethod
    def recommend(self, client_data, limit):
        """Return a list of recommendations for the given client."""
        pass

    def __str__(self):
        return self.__class__.__name__
