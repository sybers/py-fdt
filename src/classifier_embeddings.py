import sys
import spacy
import numpy as np

from gensim.models import KeyedVectors

from keras.layers import Dense, LSTM, Embedding, Dropout, Bidirectional, Input, Flatten
from keras.models import Model
from keras import optimizers
from keras.callbacks import EarlyStopping
from keras.preprocessing.sequence import pad_sequences

from datatools import load_dataset

from sklearn.preprocessing import LabelBinarizer
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from nltk import word_tokenize

np.random.seed(15)
nlp = spacy.load('fr')

class Classifier:
    """The Classifier"""

    def __init__(self):
        self.embedding_model_path = "../data/frWac_no_postag_no_phrase_500_cbow_cut100.bin"
        self.embedding_dims = 500
        self.embedding_model = None
        self.labelset = None
        self.label_binarizer = LabelBinarizer()
        self.model = None
        self.epochs = 100
        self.sequence_length = 30
        self.batchsize = 8

        # load the pre compiled embedding model from the disk
        self.load_embedding_model()

    def load_embedding_model(self):
        """Load the binary embedding from the file system"""
        self.embedding_model = KeyedVectors.load_word2vec_format(
            self.embedding_model_path,
            binary=True,
            encoding='UTF-8',
            unicode_errors='ignore'
        )

        print("Vector size is %d" % len(self.embedding_model.vocab))

    def tokenize(self, text):
        """Customized tokenizer.
        Here you can add other linguistic processing and generate more normalized features
        """
        doc = nlp(text)
        tokens = []
        for sent in doc.sents:
            for token in sent:
                if token.pos_ in ["ADJ", "NOUN", "VERB"] and token.is_stop is not True:
                    tokens.append(token.lemma_.strip().lower())
        # tokens = [t for t in tokens if t not in self.stopset]
        return tokens

    def vectorize(self, texts):
        """get the vectorized representation for the texts"""
        all_vectors = []
        for text in texts:
            text_vectors = []
            tokens = self.tokenize(text)
            for t in tokens:
                try:
                    text_vectors.append(self.embedding_model.get_vector(t))
                except KeyError:
                    # print("Skipping missing word \"%s\" from vocabulary" % word)
                    pass
            all_vectors.append(text_vectors)
        return pad_sequences(all_vectors, maxlen=self.sequence_length)

    def create_model(self):
        """Create a neural network model and return it.
        Here you can modify the architecture of the model (network type, number of layers, number of neurones)
        and its parameters"""

        input = Input((self.sequence_length, self.embedding_dims))
        layer = input

        layer = Bidirectional(LSTM(64, return_sequences=True), merge_mode="concat")(layer)
        layer = Dropout(0.2)(layer)
        layer = Flatten()(layer)
        output = Dense(len(self.labelset), activation="softmax")(layer)

        model = Model(inputs=input, outputs=output)

        # compile model
        model.compile(optimizer=optimizers.Adam(),
                      loss='categorical_crossentropy',
                      metrics=['accuracy'])
        model.summary()
        return model

    def train_on_data(self, texts, labels, valtexts=None, vallabels=None):
        """Train the model using the list of text examples together with their true (correct) labels"""
        # create the binary output vectors from the correct labels
        Y_train = self.label_binarizer.fit_transform(labels)
        # get the set of labels
        self.labelset = set(self.label_binarizer.classes_)
        print("LABELS: %s" % self.labelset)
        # build the feature index (unigram of words, bi-grams etc.)  using the training data
        # self.vectorizer.fit(texts)
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
            verbose=2
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