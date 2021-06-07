
import sys
from os import listdir, mkdir
from os.path import isfile, isdir, join, basename
from mido import MidiFile, MidiTrack, MetaMessage
from mido import second2tick
from tqdm import tqdm
import argparse


# Events to ignore while splitting the MIDI file
IGNORE_MESSAGES_TYPE = ['text', 'lyrics', 'copyright', 'track_name', 'marker', 'cue_marker']


def split_midi(input_filename, output_dir, trim_silence=True, ignore_meta=True, split_dir=None, cutoff=None, offset=None):
	""" Splits a given midi file into several files corresponding to each channel.
	"""

	# Open source file
	midi = MidiFile(input_filename)
	# print("Processing file {}".format(input_filename))

	# Initialize individual tracks to hold each channel of the original file
	new_tracks = {}
	for channel in range(16):
		new_tracks[channel] = MidiTrack()

	# list to control how many ticks since last message in each channel
	# This is because in MIDI each event message uses a time attribute
	# to control how long it has been since the last message
	delta_ticks = [0] * 16

	# Track the amount of ticks in each channel. Useful for cutoff.
	total_ticks = [0] * 16

	# list to keep track of which instrument is used in each channel
	instruments = [1] * 16  # default all channels to Acoustic Grand Piano

	# list to keep track of which channels have sounds 
	active_channels = [False] * 16

	# default tempo and ticks per beat
	tempo = 500000
	ticks_per_beat = midi.ticks_per_beat

	# Read source file and split channel events into individual tracks
	for track in midi.tracks:
		# print("Number of messages in track {}: {}".format(track.name, len(track)))

		for message in track:

			# Ignore messages that are irrelevant
			if ignore_meta and (type(message) == MetaMessage) and (message.type in IGNORE_MESSAGES_TYPE):
				continue

			# if the message has a channel, it should be saved in an individual track
			# otherwise, it's a control message and should be replicated across all new tracks
			try:
				channel = message.channel
			except Exception:
				channel = -1
			
			if channel == -1:
				# Add control message to all new tracks
				for channel in new_tracks:
					new_tracks[channel].append(message)
				
				# If its a tempo event, save the tempo value
				if message.type == "set_tempo":
					tempo = message.tempo
			else:


				# Adjust the delta ticks of the current message
				new_time = delta_ticks[channel] + message.time
				
				# Adjust the delta ticks of all channels to make sure timings are always correct
				delta_ticks = [delta + message.time for delta in delta_ticks]  # increase delta for all channels
				delta_ticks[channel] = 0 # reset time delta in this channel

				# avoid long periods of silence
				if trim_silence and new_time > 10000:
					new_time = 10000

				# Correct event time
				message.time = new_time if (active_channels[channel] or not trim_silence) else 0  # trick to avoid having silence at the beggining of each channel
				
				# If current message is a note, then we know this channel is active with sounds.
				if message.type == "note_on":
					active_channels[channel] = True

				# If it's an instrument change, replace the channel instrument
				# This only works if the instrument change is made at the beginning of the MIDI (the most common scenario).
				# Should be improved to further split instruments into different tracks.
				if message.type == "program_change":
					instruments[channel] = message.program

				# Update total ticks in this channel
				total_ticks[channel] += new_time

				if cutoff:
					cutoff_tick = second2tick(cutoff, ticks_per_beat, tempo)
					if total_ticks[channel] >= cutoff_tick:
						continue

				if offset:
					offset_tick = second2tick(offset, ticks_per_beat, tempo)
					if total_ticks[channel] <= offset_tick:
						continue

				# Add message to its new track
				new_tracks[channel].append(message)



	# Write the individual tracks into different MIDI files
	for channel in new_tracks:
		
		# skip tracks from empty channels
		if not active_channels[channel]:
			continue

		# build the output folder structure
		output_folder = output_dir
		if split_dir:
			dir_name = {"instrument": instruments[channel], "channel": channel, "file": basename(input_filename)[0:-4]}
			output_folder = join(output_dir, dir_name[split_dir])
			if not isdir(output_folder):
				mkdir(output_folder)

		output_filename = join(output_folder, "{}_ch{}_{}.mid".format(instruments[channel], channel, basename(input_filename)[0:-4]))
		
		# create a new MIDI file
		output_file = MidiFile(type=0)
		output_file.ticks_per_beat = midi.ticks_per_beat
		output_file.tracks = [ new_tracks[channel] ]
		output_file.save(output_filename)


def build_argument_parser():
	""" Create a command line parser with several options.
		The tool can accept a filename or a director as input.
	"""
	parser = argparse.ArgumentParser(description='Split a MIDI file/directory into its channels. Each channel will become a file.\nExample:\n\tmidi_splitter.py -i music.mid -trim results')
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument('-i', dest='input_filename', help='the MIDI file to split')
	group.add_argument('-d', dest='input_directory', help='alternatively, a directory with MIDI files to split')
	parser.add_argument('output_dir', help='output directory')
	parser.add_argument('-trim', action='store_true', help='trim long silences')
	parser.add_argument('-ignore', action='store_true', help='ignore useless meta events, such as lyrics')
	parser.add_argument('-offset', metavar='seconds', type=int, default=None, help='time at which to start splitting each file')
	parser.add_argument('-cutoff', metavar='seconds', type=int, default=None, help='time at which to stop splitting each file')
	parser.add_argument('-split_dir', choices=('instrument', 'channel', 'file'), default=None, help='Save the output files into different directories according to instrument/channel/file')
	return parser


if __name__ == "__main__":
	
	# Parse command line inputs
	parser = build_argument_parser()
	args = parser.parse_args()

	if args.trim:
		print("Triming of silences selected.")

	if args.ignore:
		print("Ignoring useless meta events.")

	# Build list of target MIDI files
	if args.input_filename:
		files = [ args.input_filename ]
		print("Processing MIDI file {}".format(args.input_filename))
	else:
		# Get all MIDI files in the target directory
		d = args.input_directory
		files = [join(d, f) for f in listdir(d) if isfile(join(d, f)) and f.lower().endswith(".mid")]
		print("Processing directory with {} MIDI files.".format(len(files)))
	
	# Create output directory if necessary
	if not isdir(args.output_dir):
		mkdir(args.output_dir)

	# Progress bar
	pbar = tqdm(total=len(files), bar_format="{l_bar}{bar}|", ncols=100)

	# Split each file into its channels
	for file in files:
		
		# Update progress bar description
		pbar.set_description(file)
		
		# Split file
		split_midi(file, args.output_dir, args.trim, args.ignore, args.split_dir, args.cutoff, args.offset)

		# Update progress bar
		pbar.update(1)

	# Terminate progress bar
	pbar.close()

