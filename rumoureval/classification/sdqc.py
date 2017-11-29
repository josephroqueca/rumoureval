"""Package for classifying tweets by Support, Deny, Query, or Comment (SDQC)."""

import logging
from pprint import pprint
from time import time
from sklearn import metrics
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC
from sklearn.pipeline import FeatureUnion, Pipeline
from ..pipeline.item_selector import ItemSelector
from ..pipeline.feature_counter import FeatureCounter
from ..pipeline.pipelinize import pipelinize
from ..pipeline.tweet_detail_extractor import TweetDetailExtractor
from ..util.lists import list_to_str, dict_product
from ..util.log import get_log_separator


LOGGER = logging.getLogger()
CLASSES = ['comment', 'deny', 'query', 'support']


def filter_tweets(tweets, filter_short=False, similarity_threshold=0.9):
    """Filter tweets which are believed to cause additional confusion in the classifier.

    :param tweets:
        list of twitter threads to train model on
    :type tweets:
        `list` of :class:`Tweet`
    :param filter_short:
        True to filter tweets which are too short to be meaningful
    :type filter_short:
        `bool`
    :param similarity_threshold:
        filter tweets which are this similar or more to their root tweet
    :type similarity_threshold:
        `float`
    :rtype:
        `list` of :class:`Tweet`
    """
    # Cached root tweet text
    root_cache = {}

    filtered_tweets = []
    for tweet in tweets:
        root_tweet = tweet
        while root_tweet.parent() is not None:
            root_tweet = root_tweet.parent()

        # Root tweets should not be filtered
        if root_tweet == tweet:
            filtered_tweets.append(tweet)
            continue

        # Get text of tweet and root tweet
        root_text = root_cache[root_tweet['id']] if root_tweet['id'] in root_cache else (
            TweetDetailExtractor.get_parseable_tweet_text(root_tweet)
        )
        root_cache[root_tweet['id']] = root_text

        tweet_text = TweetDetailExtractor.get_parseable_tweet_text(tweet)

        # Discard training tweet if too short
        if filter_short and len(tweet_text.split(' ')) < 3:
            continue

        # Calculate cosine similarity between tweet and root and discard if too similar
        tfidf_vectorizer = TfidfVectorizer()
        tfidf_matrix = tfidf_vectorizer.fit_transform((root_text, tweet_text))

        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix)
        if similarity[0][1] < similarity_threshold:
            filtered_tweets.append(tweet)

    return filtered_tweets


def sdqc(tweets_train, tweets_eval, train_annotations, eval_annotations):
    """
    Classify tweets into one of four categories - support (s), deny (d), query(q), comment (c).

    :param tweets_train:
        list of twitter threads to train model on
    :type tweets_train:
        `list` of :class:`Tweet`
    :param tweets_eval:
        set of twitter threads to evaluate model on
    :type tweets_eval:
        `list` of :class:`Tweet`
    :param train_annotations:
        sqdc task annotations for training data
    :type train_annotations:
        `dict
    :param eval_annotations:
        sqdc task annotations for evaluation data
    :type eval_annotations:
        `dict`
    :rtype:
        `dict`
    """
    # pylint:disable=too-many-locals
    LOGGER.info(get_log_separator())
    LOGGER.info('Beginning SDQC Task (Task A)')

    LOGGER.info('Filter tweets from training set')
    tweets_train = filter_tweets(tweets_train)

    LOGGER.info('Initializing pipeline')

    LOGGER.info('Deny pipeline')
    deny_pipeline = build_deny_pipeline()
    deny_annotations = generate_one_vs_rest_annotations(train_annotations, 'deny')
    eval_annotations_deny = generate_one_vs_rest_annotations(eval_annotations, 'deny')
    LOGGER.info(deny_pipeline)

    LOGGER.info('Query pipeline')
    query_pipeline = build_query_pipeline()
    query_annotations = generate_one_vs_rest_annotations(train_annotations, 'query')
    eval_annotations_query = generate_one_vs_rest_annotations(eval_annotations, 'query')
    LOGGER.info(query_pipeline)

    LOGGER.info('Base pipeline')
    base_pipeline = build_base_pipeline()
    LOGGER.info(base_pipeline)

    y_train_base = [train_annotations[x['id_str']] for x in tweets_train]
    y_train_deny = [deny_annotations[x['id_str']] for x in tweets_train]
    y_train_query = [query_annotations[x['id_str']] for x in tweets_train]
    y_eval_base = [eval_annotations[x['id_str']] for x in tweets_eval]
    y_eval_deny = [eval_annotations_deny[x['id_str']] for x in tweets_eval]
    y_eval_query = [eval_annotations_query[x['id_str']] for x in tweets_eval]

    LOGGER.info('Beginning training')

    # Training on tweets_train
    print('============================================================')
    print('|                                                          |')
    print('|                       base_grid                          |')
    print('|                                                          |')
    print('============================================================')
    start_time = time()
    base_grid = GridSearchCV(
        estimator=base_pipeline,
        param_grid={
            # 'union__transformer_weights': list(dict_product({
            #     'tweet_text': [1.0],

            #     'verified': [0.5],
            #     'is_news': [1.0, 5.0, 10.0, 20.0],
            #     'is_root': [1.0, 5.0, 10.0, 20.0],

            #     'count_periods': [0.5],
            #     'count_question_marks': [0.5],
            #     'count_exclamations': [0.5],
            #     'count_chars': [0.5],

            #     'count_hashtags': [0.5],
            #     'count_mentions': [0.5],
            #     'count_retweets': [0.5],
            #     'count_depth': [0.5],

            #     'pos_neg_sentiment': [1.0],
            #     'denying_words': [1.0, 5.0, 10.0, 20.0],
            #     'querying_words': [1.0, 5.0, 10.0, 20.0],
            #     'offensiveness': [1.0, 5.0, 10.0, 20.0],

            # })),
            # 'classifier__C': [1, 10, 100],
            # 'classifier__gamma': [0.001, 0.0001],
            # 'classifier__kernel': ['rbf', 'poly'],
        }
    )
    base_grid.fit(tweets_train, y_train_base)
    LOGGER.info("base_grid training: %0.3fs", time() - start_time)

    print('Best base_grid score:', base_grid.best_score_)
    pprint(base_grid.best_estimator_.steps[1][1].transformer_weights)
    print('C:\t', base_grid.best_estimator_.steps[2][1].C)
    print('gamma:\t', base_grid.best_estimator_.steps[2][1].gamma)
    print('kernel:\t', base_grid.best_estimator_.steps[2][1].kernel)

    print('============================================================')
    print('|                                                          |')
    print('|                       deny_grid                          |')
    print('|                                                          |')
    print('============================================================')
    start_time = time()
    deny_grid = GridSearchCV(
        estimator=deny_pipeline,
        param_grid={
            # 'union__transformer_weights': list(dict_product({
            #     'tweet_text': [1.0],

            #     'count_ellipsis': [2.5, 5.0, 10.0],
            #     'count_question_marks': [2.5, 5.0, 10.0],

            #     'count_depth': [1.0],

            #     'is_news': [1.0, 2.5, 5.0],
            #     'is_root': [1.0, 2.5, 5.0],

            #     'pos_neg_sentiment': [0.5, 1.0, 2.0],
            #     'denying_words': [1.0, 5.0, 10.0],
            #     'querying_words': [1.0, 5.0, 10.0],
            #     'offensiveness': [1.0, 5.0, 10.0],

            # })),
            # 'classifier__C': [1, 10, 100],
            # 'classifier__kernel': ['linear'],
            # 'classifier__class_weight': ['balanced'],
        }
    )
    deny_grid.fit(tweets_train, y_train_deny)
    LOGGER.info("deny_grid training: %0.3fs", time() - start_time)

    print('Best deny_grid score:', deny_grid.best_score_)
    pprint(deny_grid.best_estimator_.steps[1][1].transformer_weights)
    print('C:\t', deny_grid.best_estimator_.steps[2][1].C)

    print('============================================================')
    print('|                                                          |')
    print('|                      query_grid                          |')
    print('|                                                          |')
    print('============================================================')
    start_time = time()
    query_grid = GridSearchCV(
        estimator=query_pipeline,
        param_grid={
            # 'union__transformer_weights': list(dict_product({
            #     'count_depth': [1.0],

            #     'is_news': [1.0, 2.5, 5.0],
            #     'is_root': [1.0, 2.5, 5.0],

            #     'count_question_marks': [5.0],

            #     'pos_neg_sentiment': [0.5, 1.0, 2.0],
            #     'querying_words': [1.0, 5.0, 10.0],

            # })),
            # 'classifier__C': [1, 10, 100],
            # 'classifier__kernel': ['linear'],
            # 'classifier__class_weight': ['balanced'],
        }
    )
    query_grid.fit(tweets_train, y_train_query)
    LOGGER.info("query_grid training: %0.3fs", time() - start_time)

    print('Best query_grid score:', query_grid.best_score_)
    pprint(query_grid.best_estimator_.steps[1][1].transformer_weights)
    print('C:\t', query_grid.best_estimator_.steps[2][1].C)

    LOGGER.info("")
    LOGGER.info('Beginning evaluation')

    # Predicting classes for tweets_eval
    start_time = time()
    base_predictions = base_grid.predict(tweets_eval)
    deny_predictions = deny_grid.predict(tweets_eval)
    query_predictions = query_grid.predict(tweets_eval)

    print('============================================================')
    print('|                                                          |')
    print('|                  Misclassified - query                   |')
    print('|                                                          |')
    print('============================================================')

    # Print misclassified query vs not_query
    for i, prediction in enumerate(query_predictions):
        if (prediction == 'query' and y_eval_base[i] != 'query') or (prediction == 'not_query' and y_eval_base[i] == 'query'):
            root = tweets_eval[i]
            while root.parent() != None:
                root = root.parent()
            print('{}\t{}\t{}\n\t\t{}'.format(
                y_eval_base[i],
                prediction,
                TweetDetailExtractor.get_parseable_tweet_text(tweets_eval[i]),
                TweetDetailExtractor.get_parseable_tweet_text(root)
                ))

    print('============================================================')
    print('|                                                          |')
    print('|                  Misclassified - deny                    |')
    print('|                                                          |')
    print('============================================================')

    # Print misclassified deny vs not_deny
    for i, prediction in enumerate(deny_predictions):
        if (prediction == 'deny' and y_eval_base[i] != 'deny') or (prediction == 'not_deny' and y_eval_base[i] == 'deny'):
            root = tweets_eval[i]
            while root.parent() != None:
                root = root.parent()
            print('{}\t{}\t{}\n\t\t{}'.format(
                y_eval_base[i],
                prediction,
                TweetDetailExtractor.get_parseable_tweet_text(tweets_eval[i]),
                TweetDetailExtractor.get_parseable_tweet_text(root)
                ))

    predictions_wo_deny = []
    predictions_w_deny = []
    for i in range(len(base_predictions)):
        if base_predictions[i] == 'comment':
            predictions_wo_deny.append('comment')
        elif query_predictions[i] == 'query':
            predictions_wo_deny.append('query')
        else:
            predictions_wo_deny.append(base_predictions[i])

        if query_predictions[i] == 'query':
            predictions_w_deny.append('query')
        elif deny_predictions[i] == 'deny':
            predictions_w_deny.append('deny')
        else:
            predictions_w_deny.append(base_predictions[i])

    LOGGER.debug("eval time:  %0.3fs", time() - start_time)
    LOGGER.info('Completed SDQC Task (Task A). Printing results')

    # Outputting classifier results
    LOGGER.info("deny_accuracy:    %0.3f", metrics.accuracy_score(y_eval_deny, deny_predictions))
    LOGGER.info("query_accuracy:   %0.3f", metrics.accuracy_score(y_eval_query, query_predictions))
    LOGGER.info("base accuracy:    %0.3f", metrics.accuracy_score(y_eval_base, base_predictions))
    LOGGER.info("accuracy w/o d:   %0.3f", metrics.accuracy_score(y_eval_base, predictions_wo_deny))
    LOGGER.info("accuracy w/ d:    %0.3f", metrics.accuracy_score(y_eval_base, predictions_w_deny))
    LOGGER.info("classification report:")
    LOGGER.info(metrics.classification_report(y_eval_deny, deny_predictions, target_names=['deny', 'not_deny']))
    LOGGER.info(metrics.classification_report(y_eval_query, query_predictions, target_names=['not_query', 'query']))
    LOGGER.info(metrics.classification_report(y_eval_base, base_predictions, target_names=CLASSES))
    LOGGER.info(metrics.classification_report(y_eval_base, predictions_wo_deny, target_names=CLASSES))
    LOGGER.info(metrics.classification_report(y_eval_base, predictions_w_deny, target_names=CLASSES))
    LOGGER.info("confusion matrix (deny):")
    LOGGER.info(metrics.confusion_matrix(y_eval_deny, deny_predictions))
    LOGGER.info("confusion matrix (query):")
    LOGGER.info(metrics.confusion_matrix(y_eval_query, query_predictions))
    LOGGER.info("confusion matrix (base):")
    LOGGER.info(metrics.confusion_matrix(y_eval_base, base_predictions))
    LOGGER.info("confusion matrix (combined w/o deny):")
    LOGGER.info(metrics.confusion_matrix(y_eval_base, predictions_wo_deny))
    LOGGER.info("confusion matrix (combined w deny):")
    LOGGER.info(metrics.confusion_matrix(y_eval_base, predictions_w_deny))

    # Uncomment to see vocabulary
    # LOGGER.info(pipeline.get_params()['union__tweet_text__count'].get_feature_names())

    # Get the best predictions
    predictions = predictions_w_deny if metrics.accuracy_score(y_eval_base, predictions_wo_deny) < metrics.accuracy_score(y_eval_base, predictions_w_deny) else predictions_wo_deny

    # Convert results to dict of tweet ID to predicted class
    results = {}
    for (i, prediction) in enumerate(predictions):
        results[tweets_eval[i]['id_str']] = prediction

    return results


def generate_one_vs_rest_annotations(annotations, one):
    """Convert annotation labels into a set of class vs not class.

    :param annotations:
        set of annotations for tweet IDs
    :type annotations
        `dict`
    :param one:
        the one annotation vs rest
    :type one:
        `str`
    """
    one_vs_rest_annotations = {}
    for tweet_id in annotations:
        one_vs_rest_annotations[tweet_id] = \
                annotations[tweet_id] if annotations[tweet_id] == one else 'not_{}'.format(one)
    return one_vs_rest_annotations


def build_query_pipeline():
    """Build a pipeline for predicting if a tweet is classified as query or not."""
    return Pipeline([
        # Extract useful features from tweets
        ('extract_tweets', TweetDetailExtractor(task='A', strip_hashtags=False, strip_mentions=False)),

        # Combine processing of features
        ('union', FeatureUnion(
            transformer_list=[

                # Count features
                ('count_depth', Pipeline([
                    ('selector', ItemSelector(keys='depth')),
                    ('count', FeatureCounter(names='depth')),
                    ('vect', DictVectorizer()),
                ])),

                # Boolean features
                ('is_news', Pipeline([
                    ('selector', ItemSelector(keys='is_news')),
                    ('count', FeatureCounter(names='is_news')),
                    ('vect', DictVectorizer()),
                ])),

                ('is_root', Pipeline([
                    ('selector', ItemSelector(keys='is_root')),
                    ('count', FeatureCounter(names='is_root')),
                    ('vect', DictVectorizer()),
                ])),

                # Punctuation
                ('count_question_marks', Pipeline([
                    ('selector', ItemSelector(keys='question_mark_count')),
                    ('count', FeatureCounter(names='question_mark_count')),
                    ('vect', DictVectorizer()),
                ])),

                # Count positive and negative words in the tweets
                ('pos_neg_sentiment', Pipeline([
                    ('selector', ItemSelector(keys=['positive_words', 'negative_words'])),
                    ('count', FeatureCounter(names=['positive_words', 'negative_words'])),
                    ('vect', DictVectorizer()),
                ])),

                # Count querying words in the tweets
                ('querying_words', Pipeline([
                    ('selector', ItemSelector(keys='querying_words')),
                    ('count', FeatureCounter(names='querying_words')),
                    ('vect', DictVectorizer()),
                ])),

            ],

            # Relative weights of transformations
            transformer_weights={
                'count_depth': 1.0,

                'is_news': 1.0,
                'is_root': 2.5,

                'count_question_marks': 5.0,

                'pos_neg_sentiment': 0.5,
                'querying_words': 1.0,
            }


            #     'count_depth': 1.0,

            #     'is_news': 2.5,
            #     'is_root': 2.5,

            #     'count_question_marks': 5.0,

            #     'pos_neg_sentiment': 1.0,
            #     'querying_words': 5.0,
            # },

        )),

        # Use a classifier on the result
        ('classifier', SVC(C=1, kernel='linear', class_weight='balanced'))

    ])


def build_deny_pipeline():
    """Build a pipeline for predicting if a tweet is classified as deny or not."""
    return Pipeline([
        # Extract useful features from tweets
        ('extract_tweets', TweetDetailExtractor(task='A', strip_hashtags=False, strip_mentions=False)),

        # Combine processing of features
        ('union', FeatureUnion(
            transformer_list=[

                # Count occurrences on tweet text
                ('tweet_text', Pipeline([
                    ('selector', ItemSelector(keys='text_minus_root')),
                    ('list_to_str', pipelinize(list_to_str)),
                    ('count', TfidfVectorizer()),
                ])),

                # Count punctuation
                ('count_ellipsis', Pipeline([
                    ('selector', ItemSelector(keys='ellipsis_count')),
                    ('count', FeatureCounter(names='ellipsis_count')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_question_marks', Pipeline([
                    ('selector', ItemSelector(keys='question_mark_count')),
                    ('count', FeatureCounter(names='question_mark_count')),
                    ('vect', DictVectorizer()),
                ])),

                # Count features
                ('count_depth', Pipeline([
                    ('selector', ItemSelector(keys='depth')),
                    ('count', FeatureCounter(names='depth')),
                    ('vect', DictVectorizer()),
                ])),

                # Boolean features
                ('is_news', Pipeline([
                    ('selector', ItemSelector(keys='is_news')),
                    ('count', FeatureCounter(names='is_news')),
                    ('vect', DictVectorizer()),
                ])),

                ('is_root', Pipeline([
                    ('selector', ItemSelector(keys='is_root')),
                    ('count', FeatureCounter(names='is_root')),
                    ('vect', DictVectorizer()),
                ])),

                # Count positive and negative words in the tweets
                ('pos_neg_sentiment', Pipeline([
                    ('selector', ItemSelector(keys=['positive_words', 'negative_words'])),
                    ('count', FeatureCounter(names=['positive_words', 'negative_words'])),
                    ('vect', DictVectorizer()),
                ])),

                # Count denying words in the tweets
                ('denying_words', Pipeline([
                    ('selector', ItemSelector(keys='denying_words')),
                    ('count', FeatureCounter(names='denying_words')),
                    ('vect', DictVectorizer()),
                ])),

                # Count querying words in the tweets
                ('querying_words', Pipeline([
                    ('selector', ItemSelector(keys='querying_words')),
                    ('count', FeatureCounter(names='querying_words')),
                    ('vect', DictVectorizer()),
                ])),

                # Count swear words and personal attacks
                ('offensiveness', Pipeline([
                    ('selector', ItemSelector(keys=['swear_words', 'personal_words'])),
                    ('count', FeatureCounter(names=['swear_words', 'personal_words'])),
                    ('vect', DictVectorizer()),
                ])),

            ],

            # Relative weights of transformations
            transformer_weights={
                'tweet_text': 1.0,

                'count_ellipsis': 2.5,
                'count_question_marks': 2.5,

                'count_depth': 1.0,

                'is_news': 1.0,
                'is_root': 2.5,

                'pos_neg_sentiment': 0.5,
                'denying_words': 5.0,
                'querying_words': 1.0,
                'offensiveness': 5.0,
            }


            #     'tweet_text': 2.0,

            #     'count_ellipsis': 5.0,
            #     'count_question_marks': 5.0,

            #     'count_depth': 1.0,

            #     'is_news': 2.5,
            #     'is_root': 2.5,

            #     'pos_neg_sentiment': 1.0,
            #     'denying_words': 10.0,
            #     'querying_words': 10.0,
            #     'offensiveness': 10.0,
            # },

        )),

        # Use a classifier on the result
        ('classifier', SVC(C=10, kernel='linear', class_weight='balanced'))

    ])


def build_base_pipeline():
    """Build a pipeline for predicting all 4 SDQC classes."""
    return Pipeline([
        # Extract useful features from tweets
        ('extract_tweets', TweetDetailExtractor(task='A', strip_hashtags=False, strip_mentions=False)),

        # Combine processing of features
        ('union', FeatureUnion(
            transformer_list=[

                # Count occurrences on tweet text
                ('tweet_text', Pipeline([
                    ('selector', ItemSelector(keys='text_stemmed_stopped')),
                    ('list_to_str', pipelinize(list_to_str)),
                    ('count', TfidfVectorizer()),
                ])),

                # Boolean features
                ('is_news', Pipeline([
                    ('selector', ItemSelector(keys='is_news')),
                    ('count', FeatureCounter(names='is_news')),
                    ('vect', DictVectorizer()),
                ])),

                ('is_root', Pipeline([
                    ('selector', ItemSelector(keys='is_root')),
                    ('count', FeatureCounter(names='is_root')),
                    ('vect', DictVectorizer()),
                ])),

                ('verified', Pipeline([
                    ('selector', ItemSelector(keys='verified')),
                    ('count', FeatureCounter(names='verified')),
                    ('vect', DictVectorizer()),
                ])),

                # Punctuation
                ('count_periods', Pipeline([
                    ('selector', ItemSelector(keys='period_count')),
                    ('count', FeatureCounter(names='period_count')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_question_marks', Pipeline([
                    ('selector', ItemSelector(keys='question_mark_count')),
                    ('count', FeatureCounter(names='question_mark_count')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_exclamations', Pipeline([
                    ('selector', ItemSelector(keys='exclamation_count')),
                    ('count', FeatureCounter(names='exclamation_count')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_ellipsis', Pipeline([
                    ('selector', ItemSelector(keys='ellipsis_count')),
                    ('count', FeatureCounter(names='ellipsis_count')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_chars', Pipeline([
                    ('selector', ItemSelector(keys='char_count')),
                    ('count', FeatureCounter(names='char_count')),
                    ('vect', DictVectorizer()),
                ])),

                # Count features
                ('count_depth', Pipeline([
                    ('selector', ItemSelector(keys='depth')),
                    ('count', FeatureCounter(names='depth')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_hashtags', Pipeline([
                    ('selector', ItemSelector(keys='hashtags')),
                    ('count', FeatureCounter(names='hashtags')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_mentions', Pipeline([
                    ('selector', ItemSelector(keys='user_mentions')),
                    ('count', FeatureCounter(names='user_mentions')),
                    ('vect', DictVectorizer()),
                ])),

                ('count_retweets', Pipeline([
                    ('selector', ItemSelector(keys='retweet_count')),
                    ('count', FeatureCounter(names='retweet_count')),
                    ('vect', DictVectorizer()),
                ])),

                # Count positive and negative words in the tweets
                ('pos_neg_sentiment', Pipeline([
                    ('selector', ItemSelector(keys=['positive_words', 'negative_words'])),
                    ('count', FeatureCounter(names=['positive_words', 'negative_words'])),
                    ('vect', DictVectorizer()),
                ])),

                # Count denying words in the tweets
                ('denying_words', Pipeline([
                    ('selector', ItemSelector(keys='denying_words')),
                    ('count', FeatureCounter(names='denying_words')),
                    ('vect', DictVectorizer()),
                ])),

                # Count querying words in the tweets
                ('querying_words', Pipeline([
                    ('selector', ItemSelector(keys='querying_words')),
                    ('count', FeatureCounter(names='querying_words')),
                    ('vect', DictVectorizer()),
                ])),

                # Count swear words and personal attacks
                ('offensiveness', Pipeline([
                    ('selector', ItemSelector(keys=['swear_words', 'personal_words'])),
                    ('count', FeatureCounter(names=['swear_words', 'personal_words'])),
                    ('vect', DictVectorizer()),
                ])),

            ],

            # Relative weights of transformations
            transformer_weights={
                'tweet_text': 1.0,

                'verified': 0.5,
                'is_news': 5.0,
                'is_root': 20.0,

                'count_periods': 0.5,
                'count_question_marks': 0.5,
                'count_exclamations': 0.5,
                'count_chars': 0.5,

                'count_hashtags': 0.5,
                'count_mentions': 0.5,
                'count_retweets': 0.5,
                'count_depth': 0.5,

                'pos_neg_sentiment': 1.0,
                'denying_words': 1.0,
                'querying_words': 1.0,
                'offensiveness': 5.0,
            },



            # {
            #     'tweet_text': 1.0,

            #     'verified': 0.5,
            #     'is_news': 10.0,
            #     'is_root': 20.0,

            #     'count_periods': 0.5,
            #     'count_question_marks': 0.5,
            #     'count_exclamations': 0.5,
            #     'count_chars': 0.5,

            #     'count_hashtags': 0.5,
            #     'count_mentions':0.5,
            #     'count_retweets': 0.5,
            #     'count_depth': 0.5,

            #     'pos_neg_sentiment': 1.0,
            #     'denying_words': 20.0,
            #     'querying_words': 10.0,
            #     'offensiveness': 20.0,
            # },

        )),

        # Use a classifier on the result
        ('classifier', SVC(C=100, gamma=0.001, kernel='rbf'))

    ])