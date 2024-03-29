import sys
import spacy
import fr_core_news_sm
import numpy as np

from gensim.models import KeyedVectors as kv

from keras.layers import Input, Dense, Dropout, Activation, Concatenate
from keras.layers import LSTM, GRU, Embedding, Bidirectional
from keras.models import Model
from keras import optimizers
from keras.callbacks import EarlyStopping
from keras.preprocessing.sequence import pad_sequences

from datatools import load_dataset

from sklearn.preprocessing import LabelBinarizer
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
import nltk

np.random.seed(15)
nlp = fr_core_news_sm.load()

class Classifier:
    """The Classifier"""

    def __init__(self):
        self.stopwords_file = '../resources/fr_stopwords.csv'
        self.embedding_file = '../resources/frWac_non_lem_no_postag_no_phrase_200_cbow_cut100.bin'
        self.embedding_dims = 200
        self.embedding_model = None
        self.stopwords = []
        self.labelset = None
        self.label_binarizer = LabelBinarizer()
        self.model = None
        self.epochs = 25
        self.sequence_length = 35 # None for auto length
        self.batchsize = 32
        self.max_features = 9000

        self.vectorizer = CountVectorizer(
            max_features=self.max_features,
            strip_accents=None,
            analyzer='word',
            tokenizer=self.tokenize_bow,
            stop_words=None,
            ngram_range=(1, 2),
            binary=False,
            preprocessor=None
        )

        # load the pre compiled embedding model from the disk
        self.load_embedding_model()

        # load the stopwords list
        self.load_stopwords()

    def load_embedding_model(self):
        """Load the binary embedding from the file system"""
        self.embedding_model = kv.load_word2vec_format(
            self.embedding_file,
            binary=True,
            encoding='UTF-8',
            unicode_errors='ignore'
        )
        print('Vector Dictionary has %d words' % len(self.embedding_model.vocab))

    def load_stopwords(self):
        """load our custom list of stopwords"""
        with open(self.stopwords_file) as fp:
            self.stopwords = fp.read().splitlines()

    def features_count(self):
        return len(self.vectorizer.vocabulary_)

    def tokenize_embeddings(self, text):
        """Customized tokenizer.
        Here you can add other linguistic processing and generate more normalized features
        """
        doc = nlp(text)
        tokens = list()
        for sent in doc.sents:
            for token in sent:
                if token.pos_ not in ["PUNCT", "SYM", "X", "NUM"] and token.text not in self.stopwords:
                    tokens.append(token.text.lower().strip())
        return tokens

    def vectorize_embeddings(self, texts):
        """Vectorize the texts fot the word embeddings input"""
        all_indices = list()
        total_tokens = 0
        skipped_tokens = 0

        for text in texts:
            doc_indices = list()
            tokens = self.tokenize_embeddings(text)
            for t in tokens:
                total_tokens += 1
                if t in self.embedding_model:
                    doc_indices.append(self.embedding_model.vocab[t].index)
                else:
                    skipped_tokens += 1
            all_indices.append(doc_indices)

        print("Vectorizer skipped %d tokens for a total of %d tokens" % (skipped_tokens, total_tokens))
        return pad_sequences(all_indices, maxlen=self.sequence_length, value=0)

    def tokenize_bow(self, text):
        """tokenize the text for the BOW representation"""
        doc = nlp(text)
        tokens = list()
        for sent in doc.sents:
            for token in sent:
                if token.pos_ == 'NUM':
                    tokens.append('#NUM#')
                elif token.pos_ not in ["PUNCT", "SYM", "X"] and token.text not in self.stopwords:
                    tokens.append(token.lemma_.lower().strip())
        return tokens

    def vectorize_bow(self, texts):
        """Vectorize the texts for the BOW representation"""
        return self.vectorizer.transform(texts).toarray()

    def vectorize(self, texts):
        """Vectorize the texts and returns the two inputs for the model"""
        return [self.vectorize_embeddings(texts), self.vectorize_bow(texts)]

    def create_model(self):
        """Create a neural network model and return it.
        Here you can modify the architecture of the model (network type, number of layers, number of neurones)
        and its parameters"""

        # First input (word embeddings)
        input1 = Input((self.sequence_length,))
        branch1 = input1

        weights = self.embedding_model.vectors
        branch1 = Embedding(
            input_dim=weights.shape[0],
            output_dim=weights.shape[1],
            weights=[weights],
            mask_zero= True,
            trainable=False
        )(branch1)

        # branch1 = GRU(280, dropout=0.5, recurrent_dropout=0.3, activation='relu', return_sequences=True)(branch1)
        branch1 = GRU(240, dropout=0.4, recurrent_dropout=0.3, activation='relu')(branch1)
        branch1 = Dense(16, activation='relu')(branch1)

        # Second input (bag of words)
        input2 = Input((self.features_count(),))
        branch2 = input2
        branch2 = Dense(16, activation='relu')(branch2)

        # our model concatenates the two inputs
        input = Concatenate(axis=-1)([branch1, branch2])
        layer = input
        layer = Dense(16, activation='relu')(layer)

        output = Dense(len(self.labelset), activation='softmax')(layer)

        model = Model(inputs=[input1, input2], outputs=output)
        model.summary()

        # compile model
        model.compile(
            optimizer=optimizers.Adam(),
            loss='categorical_crossentropy',
            metrics=['accuracy']
        )
        return model

    def train_on_data(self, texts, labels, valtexts=None, vallabels=None):
        """Train the model using the list of text examples together with their true (correct) labels"""
        # create the binary output vectors from the correct labels
        Y_train = self.label_binarizer.fit_transform(labels)
        # get the set of labels
        self.labelset = set(self.label_binarizer.classes_)
        print('LABELS: %s' % self.labelset)
        # build the feature index (unigram of words, bi-grams etc.)  using the training data
        self.vectorizer.fit(texts)
        # create a model to train
        self.model = self.create_model()
        # for each text example, build its vector representation
        X_train = self.vectorize(texts)
        my_callbacks = []
        early_stopping = EarlyStopping(monitor='val_loss', min_delta=0, patience=3, verbose=0, mode='auto', baseline=None)
        my_callbacks.append(early_stopping)

        if valtexts is not None and vallabels is not None:
            X_val = self.vectorize(valtexts)
            Y_val = self.label_binarizer.transform(vallabels)
            valdata = (X_val, Y_val)
        else:
            valdata = None

        # Train the model!
        self.model.fit(
            X_train, Y_train,
            epochs=self.epochs,
            batch_size=self.batchsize,
            callbacks=my_callbacks,
            validation_data=valdata,
            verbose=1
        )

    def predict_on_data(self, texts):
        """Use this classifier model to predict class labels for a list of input texts.
        Returns the list of predicted labels
        """
        X = self.vectorize(texts)
        # get the predicted output vectors: each vector will contain a probability for each class label
        Y = self.model.predict(X)
        # from the output probability vectors, get the labels that got the best probability scores
        return self.label_binarizer.inverse_transform(Y)

    ####################################################################################################
    # IMPORTANT: ne pas changer le nom et les paramètres des deux méthode suivantes: train et predict
    ###################################################################################################
    def train(self, trainfile, valfile=None):
        df = load_dataset(trainfile)
        texts = df['text']
        labels = df['polarity']
        if valfile:
            valdf = load_dataset(valfile)
            valtexts = valdf['text']
            vallabels = valdf['polarity']
        else:
            valtexts = vallabels = None
        self.train_on_data(texts, labels, valtexts, vallabels)

    def predict(self, datafile):
        """Use this classifier model to predict class labels for a list of input texts.
        Returns the list of predicted labels
        """
        items = load_dataset(datafile)
        return self.predict_on_data(items['text'])
