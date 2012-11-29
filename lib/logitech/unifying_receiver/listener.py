#
#
#

import threading as _threading
from time import time as _timestamp

# for both Python 2 and 3
try:
	from Queue import Queue as _Queue
except ImportError:
	from queue import Queue as _Queue

from logging import getLogger, DEBUG as _DEBUG
_log = getLogger('LUR').getChild('listener')
del getLogger

from . import base as _base

#
#
#

class ThreadedHandle(object):
	"""A thread-local wrapper with different open handles for each thread."""

	__slots__ = ['path', '_local', '_handles']

	def __init__(self, initial_handle, path):
		assert initial_handle
		if type(initial_handle) != int:
			raise TypeError('expected int as initial handle, got %s' % repr(initial_handle))

		assert path
		self.path = path
		self._local = _threading.local()
		self._local.handle = initial_handle
		self._handles = [initial_handle]

	def _open(self):
		handle = _base.open_path(self.path)
		if handle is None:
			_log.error("%s failed to open new handle", repr(self))
		else:
			# _log.debug("%s opened new handle %d", repr(self), handle)
			self._local.handle = handle
			self._handles.append(handle)
			return handle

	def close(self):
		if self._local:
			self._local = None
			handles, self._handles = self._handles, []
			if _log.isEnabledFor(_DEBUG):
				_log.debug("%s closing %s", repr(self), handles)
			for h in handles:
				_base.close(h)

	def __del__(self):
		self.close()

	def __index__(self):
		if self._local:
			try:
				return self._local.handle
			except:
				return self._open()
	__int__ = __index__

	def __str__(self):
		if self._local:
			return str(int(self))

	def __repr__(self):
		return '<ThreadedHandle[%s]>' % self.path

	def __bool__(self):
		return bool(self._local)
	__nonzero__ = __bool__

#
#
#

_EVENT_READ_TIMEOUT = 500


class EventsListener(_threading.Thread):
	"""Listener thread for events from the Unifying Receiver.

	Incoming packets will be passed to the callback function in sequence.
	"""
	def __init__(self, receiver, events_callback):
		super(EventsListener, self).__init__(name=self.__class__.__name__)

		self.daemon = True
		self._active = False

		self.receiver = receiver
		self._queued_events = _Queue(32)
		self._events_callback = events_callback

		self.tick_period = 0

	def run(self):
		self._active = True
		_base.events_hook = self._events_hook
		ihandle = int(self.receiver.handle)
		_log.info("started with %s (%d)", self.receiver, ihandle)

		self.has_started()

		last_tick = _timestamp() if self.tick_period else 0

		while self._active:
			if self._queued_events.empty():
				try:
					# _log.debug("read next event")
					event = _base.read(ihandle, _EVENT_READ_TIMEOUT)
				except _base.NoReceiver:
					_log.warning("receiver disconnected")
					self.receiver.close()
					break

				if event:
					event = _base.make_event(*event)
			else:
				# deliver any queued events
				event = self._queued_events.get()

			if event:
				_log.debug("processing event %s", event)
				try:
					self._events_callback(event)
				except:
					_log.exception("processing event %s", event)
			elif self.tick_period:
				now = _timestamp()
				if now - last_tick >= self.tick_period:
					last_tick = now
					self.tick(now)

		_base.unhandled_hook = None
		del self._queued_events

		self.has_stopped()

	def stop(self):
		"""Tells the listener to stop as soon as possible."""
		self._active = False

	def has_started(self):
		"""Called right after the thread has started."""
		pass

	def has_stopped(self):
		"""Called right before the thread stops."""
		pass

	def tick(self, timestamp):
		"""Called about every tick_period seconds, if set."""
		pass

	def _events_hook(self, event):
		# only consider unhandled events that were sent from this thread,
		# i.e. triggered during a callback of a previous event
		if _threading.current_thread() == self:
			_log.info("queueing unhandled event %s", event)
			self._queued_events.put(event)

	def __bool__(self):
		return bool(self._active and self.receiver)
	__nonzero__ = __bool__
