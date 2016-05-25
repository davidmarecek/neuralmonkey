import tensorflow as tf
import numpy as np

from utils import log
from bidirectional_rnn_layer import BidirectionalRNNLayer
from tensorflow.models.rnn import rnn_cell
from noisy_gru_cell import NoisyGRUCell


class SentenceEncoder(object):
    def __init__(self, max_input_len, vocabulary, data_id,
                 embedding_size, rnn_size,
                 dropout_keep_p=0.5,
                 use_noisy_activations=False, attention_type=None,
                 attention_fertility=3, name="sentence_encoder", parent_encoder=None):
        self.name = name
        self.max_input_len = max_input_len
        self.vocabulary = vocabulary
        self.data_id = data_id
        self.embedding_size = embedding_size
        self.rnn_size = rnn_size
        self.max_input_len = max_input_len
        self.dropout_keep_p = dropout_keep_p
        self.use_noisy_activations = use_noisy_activations
        self.attention_type = attention_type
        self.attention_fertility = attention_fertility
        self.parent_encoder = parent_encoder

        log("Initializing sentence encoder, name: \"{}\"".format(name))
        with tf.variable_scope(name):
            self.dropout_placeholder = tf.placeholder(tf.float32, name="dropout")
            self.is_training = tf.placeholder(tf.bool, name="is_training")
            self.inputs = \
                    [tf.placeholder(tf.int32, shape=[None], name="input_{}".format(i)) for i in range(max_input_len + 2)]
            self.weight_ins = \
                    [tf.placeholder(tf.float32, shape=[None], name="input_{}".format(i)) for i in range(max_input_len + 2)]
            self.weight_tensor = tf.concat(1, [tf.expand_dims(w, 1) for w in self.weight_ins])
            self.sentence_lengths = tf.to_int64(sum(self.weight_ins))

            if parent_encoder:
                self.word_embeddings = parent_encoder.word_embeddings
            else:
                self.word_embeddings = tf.Variable(tf.random_uniform([len(vocabulary), embedding_size], -1.0, 1.0))

            embedded_inputs = [tf.nn.embedding_lookup(self.word_embeddings, input_) for input_ in self.inputs]
            dropped_embedded_inputs = [tf.nn.dropout(i, self.dropout_placeholder) for i in embedded_inputs]

            if parent_encoder:
                self.forward_gru = parent_encoder.forward_gru
                self.backward_gru = parent_encoder.backward_gru
            else:
                if use_noisy_activations:
                    self.forward_gru = NoisyGRUCell(rnn_size, self.is_training, input_size=embedding_size)
                    self.backward_gru = NoisyGRUCell(rnn_size, self.is_training, input_size=embedding_size)
                else:
                    self.forward_gru = rnn_cell.GRUCell(rnn_size, input_size=embedding_size)
                    self.backward_gru = rnn_cell.GRUCell(rnn_size, input_size=embedding_size)

            bidi_layer = BidirectionalRNNLayer(self.forward_gru,
                                               self.backward_gru,
                                               dropped_embedded_inputs,
                                               self.sentence_lengths)

            self.outputs_bidi = bidi_layer.outputs_bidi
            self.encoded = bidi_layer.encoded

            self.attention_tensor = \
                    tf.concat(1, [tf.expand_dims(o, 1) for o in self.outputs_bidi])

            self.attention_object = attention_type(self.attention_tensor,
                                                   scope="attention_{}".format(name),
                                                   dropout_placeholder=self.dropout_placeholder,
                                                   input_weights=self.weight_tensor,
                                                   max_fertility=attention_fertility) if attention_type else None

            log("Sentence encoder initialized")


    def feed_dict(self, dataset, batch_size, train=False, dicts=None):
        sentences = dataset.series[self.data_id]
        if dicts is None:
            dicts = [{} for _ in range(len(sentences) / batch_size +
                                       int(len(sentences) % batch_size > 0))]

        for fd, start in zip(dicts, range(0, len(sentences), batch_size)):
            this_sentences = sentences[start:start + batch_size]
            fd[self.sentence_lengths] = np.array([min(self.max_input_len,
                                                      len(s)) + 2 for s in this_sentences])
            vectors, weights = \
                    self.vocabulary.sentences_to_tensor(this_sentences,
                                                        self.max_input_len, train=train)
            for words_plc, words_tensor in zip(self.inputs, vectors):
                fd[words_plc] = words_tensor
            fd[self.weight_ins[0]] = np.ones(len(this_sentences))
            for weights_plc, weight_vector in zip(self.weight_ins[1:], weights):
                fd[weights_plc] = weight_vector

            if train:
                fd[self.dropout_placeholder] = self.dropout_keep_p
            else:
                fd[self.dropout_placeholder] = 1.0
            fd[self.is_training] = train

        return dicts
