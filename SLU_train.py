import os
import argparse
import logging
import sys
import tensorflow as tf
import numpy as np
from tensorflow.contrib.rnn.python.ops import core_rnn_cell
import math
from data_utils import *
from SLU_utils import createVocabulary, loadVocabulary, computeF1Score, DataProcessor
from models.models import NLUModel

parser = argparse.ArgumentParser()

parser.add_argument("--test", action="store_true", default=False, help="Whether to restore.")
parser.add_argument("--num_units", type=int, default=64, help="Network size.", dest='layer_size')
parser.add_argument("--model_type", type=str, default='full', help="""full(default) | intent_only
                                                                    full: full attention model
                                                                    intent_only: intent attention model""")
parser.add_argument("--id", type=str, default="baseline", help="The id of the model")
parser.add_argument("--batch_size", type=int, default=32, help="Batch size.")
parser.add_argument("--max_epochs", type=int, default=100, help="Max epochs to train.")
parser.add_argument("--cutoff", type=int, default=10000, help="The cut off frequency")
parser.add_argument("--dataset", type=str, default=None, help="""Type 'atis' or 'snips' to use dataset provided by us or enter what ever you named your own dataset. Note, if you don't want to use this part, enter --dataset=''. It can not be None""")
parser.add_argument("--model_path", type=str, default='./SLU-model', help="Path to save model.")
parser.add_argument("--vocab_path", type=str, default='./SLU-vocab', help="Path to vocabulary files.")
parser.add_argument("--variational", default=False, action='store_true', help="Whether to use variational training")
parser.add_argument("--l1", default=False, action="store_true")
parser.add_argument("--compress", default=False, action="store_true")
parser.add_argument("--bound", default=False, action="store_true")
#Data
parser.add_argument("--train_data_path", type=str, default='train', help="Path to training data files.")
parser.add_argument("--test_data_path", type=str, default='test', help="Path to testing data files.")
parser.add_argument("--valid_data_path", type=str, default='valid', help="Path to validation data files.")
parser.add_argument("--input_file", type=str, default='seq.in', help="Input file name.")
parser.add_argument("--slot_file", type=str, default='seq.out', help="Slot file name.")
parser.add_argument("--intent_file", type=str, default='label', help="Intent file name.")

arg=parser.parse_args()

#Print arguments
for k,v in sorted(vars(arg).items()):
    print(k,'=',v)
print()

if arg.model_type == 'full':
    add_final_state_to_intent = True
    remove_slot_attn = False
elif arg.model_type == 'intent_only':
    add_final_state_to_intent = True
    remove_slot_attn = True
else:
    print('unknown model type!')
    exit(1)

#full path to data will be: ./data + dataset + train/test/valid
if arg.dataset == None:
    print('name of dataset can not be None')
    exit(1)
elif arg.dataset == 'snips':
    print('use snips dataset')
elif arg.dataset == 'atis':
    print('use atis dataset')
else:
    print('use own dataset: ',arg.dataset)

full_train_path = os.path.join('./SLU-data',arg.dataset,arg.train_data_path)
full_test_path = os.path.join('./SLU-data',arg.dataset,arg.test_data_path)
full_valid_path = os.path.join('./SLU-data',arg.dataset,arg.valid_data_path)
test_in_path = os.path.join(full_test_path, arg.input_file)
test_slot_path = os.path.join(full_test_path, arg.slot_file)
test_intent_path = os.path.join(full_test_path, arg.intent_file)

in_vocab = build_SLU_word_dict(os.path.join(full_train_path, "seq.in"), '{}-data-{}'.format(arg.dataset, arg.cutoff), cutoff=arg.cutoff, stopword=True)
slot_vocab = build_SLU_word_dict(os.path.join(full_train_path, "seq.out"), '{}-slot'.format(arg.dataset), cutoff=None, stopword=True)
intent_vocab = build_SLU_word_dict(os.path.join(full_train_path, "label"), '{}-intent'.format(arg.dataset), cutoff=None, stopword=True)
vocabulary_size = len(in_vocab['vocab'])

with tf.variable_scope('model'):
    model = NLUModel(vocabulary_size, len(intent_vocab['vocab']), layer_size=arg.layer_size, batch_size=arg.batch_size, is_training=True, variational=arg.variational, l1=arg.l1, compress=arg.compress)
with tf.variable_scope('model', reuse=True):
    test_model = NLUModel(vocabulary_size, len(intent_vocab['vocab']), layer_size=arg.layer_size, batch_size=arg.batch_size, is_training=False, variational=arg.variational, l1=arg.l1, compress=arg.compress)

logging.basicConfig(format='%(asctime)s : %(levelname)s : %(message)s', level=logging.INFO)

saver = tf.train.Saver()

def valid(in_path, slot_path, intent_path):
    data_processor_valid = DataProcessor(in_path, slot_path, intent_path, in_vocab, slot_vocab, intent_vocab)
    sum_accuracy, cnt = 0, 0
    while True:
        in_data, slot_data, slot_weight, length, intents, in_seq, slot_seq, intent_seq = data_processor_valid.get_batch(arg.batch_size)
        train_feed_dict = {
            test_model.x: in_data,
            test_model.y: intents,
            test_model.sequence_length: length,
            test_model.threshold: 3.0,
            test_model.l1_threshold: 1e-4
        }
        _, accuracy = sess.run([test_model.predictions, test_model.accuracy], feed_dict=train_feed_dict) 
        sum_accuracy += accuracy
        cnt += 1
        if data_processor_valid.end == 1:
            break

    test_accuracy = sum_accuracy / cnt
    logging.info('intent accuracy: ' + str(test_accuracy))
    data_processor_valid.close()

# Start Training
if arg.variational:
	model_folder = "{}_models/{}_{}_variational".format(arg.dataset, arg.id, arg.layer_size)
elif arg.l1:
	model_folder = "{}_models/{}_{}_l1".format(arg.dataset, arg.id, arg.layer_size)
else:
	model_folder = "{}_models/{}_{}".format(arg.dataset, arg.id, arg.layer_size)
if not os.path.exists(model_folder):
	os.mkdir(model_folder)

with tf.Session() as sess:
    sess.run(tf.global_variables_initializer())
    logging.info('Training Start')
    
    model_name = os.path.join(model_folder, "model.ckpt")
    if tf.train.checkpoint_exists(model_name):
		saver.restore(sess, model_name)
		logging.info('Restored from previous model: {}'.format(model_name))
    
    if arg.compress and arg.variational:
        vocab = []
        metrics = []
        ratios = sess.run(test_model.embedding.embedding_logdropout_ratio).squeeze()
        ratios.sort()
        #log_dropout = sess.run(test_model.embedding.embedding_logdropout_ratio)
        intervals = list(np.linspace(3, 100, 40)) + list(np.linspace(100, vocabulary_size - 1, 60))
        intervals = [ratios[int(_)] + 1e-5 for _ in intervals]
        for t in intervals:
            data_processor_valid = DataProcessor(test_in_path, test_slot_path, test_intent_path, in_vocab, slot_vocab, intent_vocab)
            sum_accuracy, cnt = 0, 0
            while True:
                in_data, slot_data, slot_weight, length, intents, in_seq, slot_seq, intent_seq = data_processor_valid.get_batch(arg.batch_size)
                train_feed_dict = {
                    test_model.x: in_data,
                    test_model.y: intents,
                    test_model.sequence_length: length,
                    test_model.threshold: t
                }
                _, accuracy = sess.run([test_model.predictions, test_model.accuracy], feed_dict=train_feed_dict) 
                sum_accuracy += accuracy
                cnt += 1
                if data_processor_valid.end == 1:
                    break

            test_accuracy = sum_accuracy / cnt
            sparsity = sess.run(test_model.sparsity, feed_dict={test_model.threshold:t})
            rest_words = int((1 - sparsity) * vocabulary_size)
            if rest_words > 1:
                metrics.append(test_accuracy)
                vocab.append(rest_words)
                data_processor_valid.close() 

        print metrics
        print vocab
        print("ROC={} CR={}".format(ROC(metrics, vocab), CR(metrics, vocab)))
    elif arg.compress and arg.bound:
        vocab = []
        metrics = []
        intervals = list(np.linspace(3, 100, 40)) + list(np.linspace(100, vocabulary_size, 60))
        for t in intervals:
            t = int(t)
            zeros = np.zeros((vocabulary_size, 1), 'float32')
            for _ in range(20):
                t = np.random.choice(range(vocabulary_size), t)
                zeros[t, :] = 1
                sum_accuracy, cnt = 0, 0
                data_processor_valid = DataProcessor(test_in_path, test_slot_path, test_intent_path, in_vocab, slot_vocab, intent_vocab)
                sum_accuracy, cnt = 0, 0
                while True:
                    in_data, slot_data, slot_weight, length, intents, in_seq, slot_seq, intent_seq = data_processor_valid.get_batch(arg.batch_size)
                    train_feed_dict = {
                        test_model.x: in_data,
                        test_model.y: intents,
                        test_model.sequence_length: length,
                        test_model.mask: zeros
                    }
                    _, accuracy = sess.run([test_model.predictions, test_model.accuracy], feed_dict=train_feed_dict) 
                    sum_accuracy += accuracy
                    cnt += 1
                    if data_processor_valid.end == 1:
                        break

                test_accuracy = sum_accuracy / cnt
                metrics.append(test_accuracy)
                vocab.append(t)
                data_processor_valid.close()
        print(metrics)
        print(vocab)
        sys.exit(1)

    elif arg.compress:
        vocab = []
        metrics = []
        intervals = list(np.linspace(3, 100, 40)) + list(np.linspace(100, vocabulary_size, 60))
        for t in intervals:
            t = int(t)
            zeros = np.zeros((vocabulary_size, 1), 'float32')
            zeros[:t, :] = 1

            sum_accuracy, cnt = 0, 0
            data_processor_valid = DataProcessor(test_in_path, test_slot_path, test_intent_path, in_vocab, slot_vocab, intent_vocab)
            sum_accuracy, cnt = 0, 0
            while True:
                in_data, slot_data, slot_weight, length, intents, in_seq, slot_seq, intent_seq = data_processor_valid.get_batch(arg.batch_size)
                train_feed_dict = {
                    test_model.x: in_data,
                    test_model.y: intents,
                    test_model.sequence_length: length,
                    test_model.mask: zeros
                }
                _, accuracy = sess.run([test_model.predictions, test_model.accuracy], feed_dict=train_feed_dict) 
                sum_accuracy += accuracy
                cnt += 1
                if data_processor_valid.end == 1:
                    break

            test_accuracy = sum_accuracy / cnt
            metrics.append(test_accuracy)
            vocab.append(t)
            data_processor_valid.close() 
        print metrics
        print vocab
        print("ROC={} CR={}".format(ROC(metrics, vocab), CR(metrics, vocab)))
        sys.exit(1)
    
    epochs = 0
    loss = 0.0
    data_processor = None
    num_loss = 0
    step = 0
    no_improve = 0

    #variables to store highest values among epochs, only use 'valid_err' for now
    valid_slot = 0
    test_slot = 0
    valid_intent = 0
    test_intent = 0
    valid_err = 0
    test_err = 0

    while True:
        if data_processor == None:
            data_processor = DataProcessor(os.path.join(full_train_path, arg.input_file), os.path.join(full_train_path, arg.slot_file), os.path.join(full_train_path, arg.intent_file), in_vocab, slot_vocab, intent_vocab)
        in_data, slot_data, slot_weight, length, intents, _, _, _ = data_processor.get_batch(arg.batch_size)
        #cur_decay = min(math.pow(10, epochs // 3) * 0.00001, 0.01)
        cur_decay = 0.0001
        learning_rate = 1e-2
        train_feed_dict = {
            model.x: in_data,
            model.y: intents,
            model.sequence_length: length,
            model.weight_decay: cur_decay,
            model.learning_rate: learning_rate,
            model.threshold: 3.0,
            model.l1_threshold: 1e-4
        }

        if arg.variational:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)
        elif arg.l1:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)
        else:
            _, step, loss, reg_loss, sparsity = sess.run([model.optimizer, model.global_step, model.cross_entropy, model.reg_loss, model.sparsity], feed_dict=train_feed_dict)

        if step % 100 == 0:
            print("epoch {0}: KL_decay {1}: step {2}: cross_entropy = {3}: reg_loss = {4}, sparsity = {5}: full_vocab = {6}: remaining_vocab: {7}".format(epochs, cur_decay, step, loss, reg_loss, sparsity, vocabulary_size, int((1 - sparsity) * vocabulary_size)))

        if data_processor.end == 1:
            data_processor.close()
            data_processor = None
            epochs += 1
            #valid(os.path.join(full_valid_path, arg.input_file), \
            #      os.path.join(full_valid_path, arg.slot_file), \
            #      os.path.join(full_valid_path, arg.intent_file))
            valid(test_in_path, test_slot_path, test_intent_path)
            #save_path = os.path.join(arg.model_path,'_step_' + str(step) + '_epochs_' + str(epochs) + '.ckpt')
            saver.save(sess, model_name)
            if epochs == arg.max_epochs:
                break
