import sys
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
import pyqtgraph as pg
import socket
import threading

DEFAULT_MCAST_GROUP = "224.3.11.15"
DEFAULT_MCAST_PORT = 31115
DEFAULT_LISTEN_ADDR = "0.0.0.0"
DEFAULT_LISTEN_PORT = 0

class Device:
    def __init__(self, modelNum, serialNum, ipAddress, port):
        self.modelNum = modelNum
        self.serialNum = serialNum
        self.ipAddress = ipAddress
        self.port = port
        self.running = False

class DeviceDiscovery(QtCore.QObject):
    deviceFound = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.devices = {}
        self.devicesList = []

    def startDiscovery(self):
        thread = threading.Thread(target=self.sendDiscovery, args=(DEFAULT_MCAST_GROUP, DEFAULT_MCAST_PORT), daemon=True)
        thread.start()

    def sendDiscovery(self, group, port, message='ID;'):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        try:
            print(f"Sending message to {group}:{port}")
            msg = message.encode("latin1")
            sock.sendto(msg, (DEFAULT_MCAST_GROUP, DEFAULT_MCAST_PORT))
            print("Message sent.")

            sock.settimeout(3)
            while True:
                data, addr = sock.recvfrom(1024)
                decoded = data.decode("latin1")
                print(decoded, "GOT EM")
                splitSemicolon = decoded.split(";")
                model = splitSemicolon[1].split('=')[1]
                serial = splitSemicolon[2].split('=')[1]
                if (model, serial) not in self.devices:
                    device = Device(model, serial, addr[0], addr[1])
                    self.devices[(model, serial)] = device
                    self.devicesList.append((model, serial))
                    self.deviceFound.emit(device)

        except socket.timeout:
            if not self.devicesList:
                print("No devices found.")
            sock.close()

class PlotWidget(QtWidgets.QWidget):
    def __init__(self, deviceName):
        super().__init__()
        self.deviceName = deviceName
        self.timeData = []
        self.mvData = []
        self.maData = []

        layout = QtWidgets.QVBoxLayout()
        self.plotWidget = pg.PlotWidget(title=f"Live Plot - {self.deviceName}")
        self.plotWidget.setBackground('w')
        self.plotWidget.addLegend()
        layout.addWidget(self.plotWidget)
        self.setLayout(layout)

        self.mvCurve = self.plotWidget.plot(pen='r', name="MV")
        self.maCurve = self.plotWidget.plot(pen='b', name="MA")

        self.plotWidget.setLabel('left', 'Value')
        self.plotWidget.setLabel('bottom', 'Time (ms)')
        self.plotWidget.showGrid(x=True, y=True)

    def updatePlot(self, timeVal, mv, ma):
        self.timeData.append(float(timeVal))
        self.mvData.append(float(mv))
        self.maData.append(float(ma))

        self.mvCurve.setData(self.timeData, self.mvData)
        self.maCurve.setData(self.timeData, self.maData)

    def clearPlot(self):
        self.timeData.clear()
        self.mvData.clear()
        self.maData.clear()
        self.mvCurve.setData([], [])
        self.maCurve.setData([], [])
        # self.plotWidget.setTitle(f"Live Plot - {self.deviceName} (Cleared)")

class TestWorker(QThread):
    dataReceived = pyqtSignal(str, float, float, float)
    testFinished = pyqtSignal(str)

    def __init__(self, deviceKey, ip, port, duration, rate):
        super().__init__()
        self.deviceKey = deviceKey
        self.ip = ip
        self.port = port
        self.duration = duration
        self.rate = rate
        self.running = True

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        startCmd = f"TEST;CMD=START;DURATION={self.duration};RATE={self.rate};"
        sock.sendto(startCmd.encode("latin1"), (self.ip, self.port))
        sock.settimeout(self.duration + 8)
        try:
            while self.running:
                data, addr = sock.recvfrom(1024)
                decoded = data.decode("latin1")
                print(decoded)

                if "STATE=IDLE" in decoded:
                    break
                if decoded.startswith("STATUS"):
                    parts = decoded.strip(';').split(';')
                    parsed = dict(part.split('=') for part in parts if '=' in part)
                    self.dataReceived.emit(self.deviceKey, float(parsed['TIME']), float(parsed['MV']), float(parsed['MA']))
        except socket.timeout:
            pass
        self.testFinished.emit(self.deviceKey)

    def stop(self):
        self.running = False
        stopCmd = "TEST;CMD=STOP;"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.sendto(stopCmd.encode("latin1"), (self.ip, self.port))

class TestGUI(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Device Test GUI")
        self.setGeometry(100, 100, 1000, 600)
        
        self.centralWidget = QtWidgets.QWidget()
        self.setCentralWidget(self.centralWidget)

        mainLayout = QtWidgets.QHBoxLayout()

        controlPanel = QtWidgets.QVBoxLayout()

        self.discoverBtn = QtWidgets.QPushButton("Discover Devices")
        controlPanel.addWidget(self.discoverBtn)
        self.testObjects = {}

        self.discoverClass = DeviceDiscovery()
        self.deviceList = self.discoverClass.devicesList
        self.deviceListWidget = QtWidgets.QListWidget()
        self.deviceListWidget.setSelectionMode(QtWidgets.QListWidget.MultiSelection)
        controlPanel.addWidget(QtWidgets.QLabel("Discovered Devices:"))
        controlPanel.addWidget(self.deviceListWidget)

        self.durationInput = QtWidgets.QSpinBox()
        self.durationInput.setRange(1, 999999999)
        self.durationInput.setSuffix(" s")
        controlPanel.addWidget(QtWidgets.QLabel("Test Duration:"))
        controlPanel.addWidget(self.durationInput)

        self.rateInput = QtWidgets.QSpinBox()
        self.rateInput.setRange(1, 999999999)
        self.rateInput.setSuffix(" s")
        controlPanel.addWidget(QtWidgets.QLabel("Result Reporting Rate:"))
        controlPanel.addWidget(self.rateInput)

        self.startBtn = QtWidgets.QPushButton("Start Test")
        self.stopBtn = QtWidgets.QPushButton("Stop Test")
        self.clearBtn = QtWidgets.QPushButton("Clear Plot")
        controlPanel.addWidget(self.startBtn)
        controlPanel.addWidget(self.stopBtn)
        controlPanel.addWidget(self.clearBtn)


        controlPanel.addWidget(QtWidgets.QLabel("Log Output:"))
        self.logOutput = QtWidgets.QTextEdit()
        self.logOutput.setReadOnly(True)
        controlPanel.addWidget(self.logOutput)

        mainLayout.addLayout(controlPanel, 3)

        self.plotTabs = QtWidgets.QTabWidget()
        mainLayout.addWidget(self.plotTabs, 13)

        self.centralWidget.setLayout(mainLayout)
        self.plotWidgets = {} #device: plotwidget
        self.testThreads = {} #device: testworker

        self.discoverBtn.clicked.connect(self.discoverDevices)
        self.startBtn.clicked.connect(self.startTest)
        self.stopBtn.clicked.connect(self.stopTest)
        self.clearBtn.clicked.connect(self.clearPlot)

    def discoverDevices(self):
        self.deviceListWidget.clear()
        self.discoverClass.sendDiscovery(DEFAULT_MCAST_GROUP, DEFAULT_MCAST_PORT)
        devices = self.discoverClass.devicesList    
        print("I am here now after discovery")

        for device in devices:
            item = QtWidgets.QListWidgetItem(f"{device[0]} - {device[1]}")
            self.deviceListWidget.addItem(item)
            self.logOutput.append("Discovered device: " + f"{device[0]} - {device[1]}")
        
        if not devices:
            self.logOutput.append("No devices found.")

    def startTest(self):
        selectedItems = self.deviceListWidget.selectedItems()
        if not selectedItems:
            self.logOutput.append("No devices selected.")
            return
        
        for i in selectedItems:
            item = i.text()
            print(item)
            model, sn = item.split(" - ")
            device = self.discoverClass.devices[(model, sn)]
            testDuration = self.durationInput.value()
            testRate = self.rateInput.value()

            if item not in self.plotWidgets:
                plot = PlotWidget(item)
                self.plotTabs.addTab(plot, item)
                self.plotWidgets[item] = plot

            thread = TestWorker(item, device.ipAddress, device.port, testDuration, testRate)
            thread.dataReceived.connect(self.updatePlot)
            thread.testFinished.connect(self.testDone)
            thread.start()
            self.testThreads[item] = thread
            self.logOutput.append(f"Started test for {item}.")

    def stopTest(self):
        selectedItems = self.deviceListWidget.selectedItems()
        if not selectedItems:
            self.logOutput.append("No devices selected for stopping testing.")
            return
        
        for i in selectedItems:
            item = i.text()
            if item in self.testThreads:
                self.testThreads[item].stop()
                self.logOutput.append(f"Stopped test for {item}.")

    def updatePlot(self, deviceKey, t, mv, ma):
        if deviceKey in self.plotWidgets:
            self.plotWidgets[deviceKey].updatePlot(t, mv, ma)
            self.logOutput.append(f"Updated plot for {deviceKey}: Time={t}, MV={mv}, MA={ma}")

    def testDone(self, deviceKey):
        self.logOutput.append(f"Test completed for {deviceKey}.")

    def clearPlot(self):
        selectedIndex = self.plotTabs.currentIndex()
        if selectedIndex >= -1:
            key = self.plotTabs.tabText(selectedIndex)
            print(key)
            if key in self.plotWidgets:
                self.plotWidgets[key].clearPlot()
                self.logOutput.append(f"Cleared plot for {key}.")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TestGUI()
    window.show()
    sys.exit(app.exec_())
