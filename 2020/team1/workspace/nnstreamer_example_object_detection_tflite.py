#!/usr/bin/env python

"""
@file		nnstreamer_example_object_detection_tflite.py
@date		4 Oct 2020
@brief		Python version of Tensor stream example with TF-Lite model for object detection
@see		https://github.com/nnsuite/nnstreamer
@author		SSAFY Team 1 <jangjongha.sw@gmail.com>
@bug		No known bugs.

This code is a Python port of Tensor stream example with TF-Lite model for object detection.

Pipeline :
v4l2src -- (TBU)

Get model by
$ cd $NNST_ROOT/bin
$ bash get-model.sh object-detection-tf

Run example :
Before running this example, GST_PLUGIN_PATH should be updated for nnstreamer plugin.
$ export GST_PLUGIN_PATH=$GST_PLUGIN_PATH:<nnstreamer plugin path>
$ python nnstreamer_example_object_detection_tflite.py

See https://lazka.github.io/pgi-docs/#Gst-1.0 for Gst API details.

Required model and resources are stored at below link
https://github.com/nnsuite/testcases/tree/master/DeepLearningModels/tensorflow-lite/ssd_mobilenet_v2_coco
"""

import os
import sys
import gi
import logging
import math

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

DEBUG = False

class NNStreamerExample:
    """NNStreamer example for Object Detection."""

    def __init__(self, argv=None):
        self.loop = None
        self.pipeline = None
        self.running = False

        self.BOX_SIZE = 4
        self.LABEL_SIZE = 91
        self.DETECTION_MAX = 1917

        self.Y_SCALE = 10.0
        self.X_SCALE = 10.0
        self.H_SCALE = 5.0
        self.W_SCALE = 5.0

        self.VIDEO_WIDTH = 640
        self.VIDEO_HEIGHT = 480
        self.MODEL_WIDTH = 300
        self.MODEL_HEIGHT = 300

        self.tflite_model = ''
        self.tflite_labels = []
        self.tflite_box_priors = []
        self.overlay_state = []
        self.detected_objects = []

        if not self.tflite_init():
            raise Exception

        GObject.threads_init()
        Gst.init(argv)

    def run_example(self):
        """Init pipeline and run example.
        :return: None
        """

        print("Run: NNStreamer example for object detection.")

        # main loop
        self.loop = GObject.MainLoop()

        # init pipeline
        self.pipeline = Gst.parse_launch(
            'v4l2src name=cam_src ! videoconvert ! videoscale ! '
            'video/x-raw,width=640,height=480,format=RGB ! tee name=t_raw '
            't_raw. ! queue ! videoconvert ! cairooverlay name=tensor_res ! ximagesink name=img_tensor '
            't_raw. ! queue leaky=2 max-size-buffers=2 ! videoscale ! video/x-raw,width=300,height=300 ! tensor_converter ! '
            'tensor_transform mode=arithmetic option=typecast:float32,add:-127.5,div:127.5 ! '
            'tensor_filter framework=tensorflow-lite model=' + self.tflite_model + ' ! '
            'tensor_sink name=tensor_sink'
        )

        # bus and message callback
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.on_bus_message)

        # tensor sink signal : new data callback
        tensor_sink = self.pipeline.get_by_name('tensor_sink')
        tensor_sink.connect('new-data', self.new_data_cb)
        
        # tensor_res = self.pipeline.get_by_name('tensor_res')
        # tensor_res.connect('draw', self.draw_overlay_cb)
        # tensor_res.connect('caps-changed', self.prepare_overlay_cb)

        # start pipeline
        self.pipeline.set_state(Gst.State.PLAYING)
        self.running = True

        self.set_window_title('img_tensor', 'NNStreamer Object Detection Example')

        # run main loop
        self.loop.run()

        # quit when received eos or error message
        self.running = False
        self.pipeline.set_state(Gst.State.NULL)

        bus.remove_signal_watch()

    def tflite_init(self):
        """
        :return: True if successfully initialized
        """
        tflite_model = 'ssd_mobilenet_v2_coco.tflite'
        tflite_label = 'coco_labels_list.txt'
        tflite_box_prior = "box_priors.txt"

        current_folder = os.path.dirname(os.path.abspath(__file__))
        model_folder = os.path.join(current_folder, 'tflite_model')

        self.tflite_model = os.path.join(model_folder, tflite_model)
        if not os.path.exists(self.tflite_model):
            logging.error('cannot find tflite model [%s]', self.tflite_model)
            return False

        label_path = os.path.join(model_folder, tflite_label)
        try:
            with open(label_path, 'r') as label_file:
                for line in label_file.readlines():
                    self.tflite_labels.append(line)
        except FileNotFoundError:
            logging.error('cannot find tflite label [%s]', label_path)
            return False

        box_prior_path = os.path.join(model_folder, tflite_box_prior)
        try:
            with open(box_prior_path, 'r') as box_prior_file:
                for line in box_prior_file.readlines():
                    datas = list(map(float, line.split()))
                    self.tflite_box_priors.append(datas)
        except FileNotFoundError:
            logging.error('cannot find tflite label [%s]', box_prior_path)
            return False

        # print("{} {}".format(len(self.tflite_labels), len(self.tflite_box_priors)))
        # print("{}".format(len(self.tflite_box_priors[0])))

        logging.info('finished to load labels, total [%d]', len(self.tflite_labels))
        logging.info('finished to load box_priors, total [%d]', len(self.tflite_box_priors))
        return True

    def on_bus_message(self, bus, message):
        """
        :param bus: pipeline bus
        :param message: message from pipeline
        :return: None
        """
        if message.type == Gst.MessageType.EOS:
            logging.info('received eos message')
            self.loop.quit()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            logging.warning('[error] %s : %s', error.message, debug)
            self.loop.quit()
        elif message.type == Gst.MessageType.WARNING:
            error, debug = message.parse_warning()
            logging.warning('[warning] %s : %s', error.message, debug)
        elif message.type == Gst.MessageType.STREAM_START:
            logging.info('received start message')
        elif message.type == Gst.MessageType.QOS:
            data_format, processed, dropped = message.parse_qos_stats()
            format_str = Gst.Format.get_name(data_format)
            logging.debug('[qos] format[%s] processed[%d] dropped[%d]', format_str, processed, dropped)

    def iou(self, A, B):
        x1 = max(A['x'], B['x'])
        y1 = max(A['y'], B['y'])
        x2 = min(A['x'] + A['width'], B['x'] + B['width'])
        y2 = min(A['y'] + A['height'], B['y'] + B['height'])
        w = max(0, (x2 - x1 + 1))
        h = max(0, (y2 - y1 + 1))
        inter = float(w * h)
        areaA = float(A['width'] * A['height'])
        areaB = float(B['width'] * B['height'])
        o = float(inter / (areaA + areaB - inter))
        return o if o >= 0 else 0

    def nms(self, detected):
        threshold_iou = 0.5
        detected = sorted(detected, key=lambda a: a['prob'])
        boxes_size = len(detected)

        _del = [False for _ in range(boxes_size)]

        for i in range(boxes_size):
            if not _del[i]:
                for j in range(i + 1, boxes_size):
                    if self.iou(detected[i], detected[j]) > threshold_iou:
                        _del[j] = True

        # update result
        self.detected_objects.clear()

        for i in range(boxes_size):
            if not _del[i]:
                self.detected_objects.append(detected[i])

                if DEBUG:
                    print("==============================")
                    print("LABEL           : {}".format(self.tflite_labels[detected[i]["class_id"]]))
                    print("x               : {}".format(detected[i]["x"]))
                    print("y               : {}".format(detected[i]["y"]))
                    print("width           : {}".format(detected[i]["width"]))
                    print("height          : {}".format(detected[i]["height"]))
                    print("Confidence Score: {}".format(detected[i]["prob"]))


    def get_detected_objects(self, detections, boxes):
        threshold_score = 0.5
        detected = list()

        for d in range(self.DETECTION_MAX):
            ycenter = boxes[0] / self.Y_SCALE * self.tflite_box_priors[2][d] + self.tflite_box_priors[0][d]
            xcenter = boxes[1] / self.X_SCALE * self.tflite_box_priors[3][d] + self.tflite_box_priors[1][d]
            h = math.exp(boxes[2] / self.H_SCALE) * self.tflite_box_priors[2][d]
            w = math.exp(boxes[3] / self.W_SCALE) * self.tflite_box_priors[3][d]

            ymin = ycenter - h / 2.0
            xmin = xcenter - w / 2.0
            ymax = ycenter + h / 2.0
            xmax = xcenter + w / 2.0

            x = xmin * self.MODEL_WIDTH
            y = ymin * self.MODEL_HEIGHT
            width = (xmax - xmin) * self.MODEL_WIDTH
            height = (ymax - ymin) * self.MODEL_HEIGHT

            for c in range(1, self.LABEL_SIZE):
                score = 1.0 / (1.0 + math.exp(-detections[c]))

                if score < threshold_score:
                    continue

                obj = {
                    'class_id': c,
                    'x': x,
                    'y': y,
                    'width': width,
                    'height': height,
                    'prob': score
                }

                detected.append(obj)
            
            # detections += self.LABEL_SIZE
            # boxes += self.BOX_SIZE
        
        self.nms(detected)

    def new_data_cb(self, sink, buffer):
        if self.running:
            if buffer.n_memory() != 2:
                return False
            
            # boxes
            mem_boxes = buffer.peek_memory(0)
            result1, info_boxes = mem_boxes.map(Gst.MapFlags.READ)
            if result1:
                assert info_boxes.size == self.BOX_SIZE * self.DETECTION_MAX * 4, "Invalid info_box size"
                boxes = info_boxes.data
            
            # detections
            mem_detections = buffer.peek_memory(1)
            result2, info_detections = mem_detections.map(Gst.MapFlags.READ)
            if result2:
                assert info_detections.size == self.LABEL_SIZE * self.DETECTION_MAX * 4, "Invalid info_detection size"
                detections = info_detections.data

            self.get_detected_objects(detections, boxes)

            mem_boxes.unmap(info_boxes)
            mem_detections.unmap(info_detections)

    def set_window_title(self, name, title):
        """Set window title.
        :param name: GstXImageasink element name
        :param title: window title
        :return: None
        """
        element = self.pipeline.get_by_name(name)
        if element is not None:
            pad = element.get_static_pad('sink')
            if pad is not None:
                tags = Gst.TagList.new_empty()
                tags.add_value(Gst.TagMergeMode.APPEND, 'title', title)
                pad.send_event(Gst.Event.new_tag(tags))
    
    # # @brief Store the information from the caps that we are interested in.
    # def prepare_overlay_cb(self, overlay, caps, user_data):
    #     pass

    # # @brief Callback to draw the overlay.
    # def draw_overlay_cb(self, overlay, cr, timestamp, duration, user_data):
    #     state = self.overlay_state

if __name__ == '__main__':
    example = NNStreamerExample(sys.argv[1:])
    example.run_example()
    
