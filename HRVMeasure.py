from machine import UART, Pin, I2C, Timer, ADC, Signal
from ssd1306 import SSD1306_I2C
from fifo import Fifo
import network
from umqtt.simple import MQTTClient
from fifo import Fifo
import time
import mip
import math
import urequests as requests
import ujson

class Encoder:
    def __init__(self, rot_a, rot_b):
        self.a = Pin(rot_a, mode = Pin.IN, pull = Pin.PULL_UP)
        self.b = Pin(rot_b, mode = Pin.IN, pull = Pin.PULL_UP)
        self.fifo = Fifo(30, typecode = 'i')
        self.a.irq(handler = self.handler, trigger = Pin.IRQ_RISING, hard = True)
    
    def handler(self, pin):
        if self.b():
            self.fifo.put(-1)
        else:
            self.fifo.put(1)

class EncoderButton:
    def __init__(self, pin):
        self.button = Pin(pin, mode = Pin.IN, pull = Pin.PULL_UP)
        self.fifo = Fifo(30, typecode = 'i')
        self.button.irq(handler = self.handler, trigger = Pin.IRQ_FALLING, hard = True)
        self.lastWrite = time.ticks_ms()
    
    def handler(self, pin):
        if time.ticks_diff(time.ticks_ms(), self.lastWrite) > 333:
            self.fifo.put(1)
            self.lastWrite = time.ticks_ms()


def connectWLAN():
    # network credentials
    SSID = "Kotipesä"
    PASSWORD = "orsacchiotto"
    
    # Connecting to the group WLAN
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)

    # Attempt to connect once per second
    while not wlan.isconnected():
        print("Connecting... ")
        time.sleep(1)

    # Print the IP address of the Pico
    print("Connection successful. Pico IP:", wlan.ifconfig()[0])
    return wlan

    
def connect_mqtt():
    BROKER_IP = "IP"
    mqtt_client=MQTTClient("", BROKER_IP)
    mqtt_client.connect(clean_session=True)
    return mqtt_client

    

RotPush = EncoderButton(Pin(12))
Rot = Encoder(Pin(10),Pin(11))

i2c = I2C(1, scl=Pin(15), sda=Pin(14), freq=400000)

oled_width = 128
oled_height = 64
oled = SSD1306_I2C(oled_width, oled_height, i2c)

wlan = connectWLAN()

def HRMeasure():
    oled.fill(0)
    pulse = ADC(Pin(26))
    led = Pin(20, Pin.OUT)

    t = time.ticks_ms()

    max_samples = 127
    peakAmount = 0
    heartRateShowCount = 0
    history = []
    for r in range(30):
        history.append(pulse.read_u16())
    time.sleep(0.15)
    peakHistory = []
    lastPeak = False
    
            
    while True:
        try:
            if RotPush.fifo.has_data():
                RotPush.fifo.get()
                return
            
            value=pulse.read_u16()
            
            if value > 50000:
                peakAmount = 0
                history = []
                oled.fill(0)
                oled.show()
                continue
            else:
                if not history:
                    for r in range(30):
                        history.append(pulse.read_u16())
                value = pulse.read_u16()
                history.append(value)
                history = history[-max_samples:]
                
                oled.fill_rect(0,10,127,63,0)
                xindx = 0
                step = (max(history) - min(history))/(oled_height-11)
                lastRead = [0, int((max(history)-history[0])/ step) + 10]
                for n in history[1:-1]:
                    readY = int((max(history)-n)/ step) + 10
                    oled.line(lastRead[0],lastRead[1], xindx, readY, 1)
                    lastRead = [xindx, readY]
                    xindx += 1
                    
                oled.show()
                
                # vc = valCount and rc = readCount, done save time
                led.off()
                
                peakHistory = peakHistory[-20:]
                diff = max(history[-15:]) - min(history[-15:])
                if value-min(history[-15:]) > diff*0.8 and time.ticks_ms() - t > 300:
                    peakHistory.append(time.ticks_ms() - t)
                    t = time.ticks_ms()
                    print("here", value)
                    oled.fill_rect(0,0,127,8,0)
                    oled.text("Hz: " + str(60/((sum(peakHistory)/1000)/len(peakHistory))), 10, 0)
                    oled.show()
                    peakAmount +=1
                    print((sum(peakHistory)/1000)/len(peakHistory))
                    lastPeak = True
                    led.on()
                else:
                    lastPeak = False
                
                
        
        except OSError as e:
            machine.reset()
            

def Measure30():
    oled.fill(0)
    oled.text("Getting Data", 7, 7, 1)
    oled.show()
    pulse = ADC(Pin(26))
    led = Pin(20, Pin.OUT)

    t = time.ticks_ms()
    tStart = t

    max_samples = 127
    peakAmount = 0
    history = []
    for r in range(30):
        history.append(pulse.read_u16())
    intervals = []
    lastPeak = t
    
            
    while time.ticks_ms() - tStart < 30000:
        try:
            if RotPush.fifo.has_data():
                RotPush.fifo.get()
                return 
            
            value=pulse.read_u16()
                
            history.append(value)
            history = history[-max_samples:]
            diff = max(history[-15:]) - min(history[-15:])
            if value-min(history[-15:]) > diff*0.8 and time.ticks_ms()-t > 300:
                intervals.append(time.ticks_ms() - t)
                t = time.ticks_ms()
                peakAmount +=1
                led.on()
            else:
                led.off()
            
            oled.fill_rect(0,15,127,67,0)
            oled.text(str(round((time.ticks_ms()-tStart)/1000)) + "/30",7,31,1)
            oled.show()

        except OSError as e:
            machine.reset()
            
    return intervals


def HRVMeasurement():
    intervals = Measure30()
    stuffDict = {}
    if not intervals:
        return
    
    while not RotPush.fifo.has_data():
        MeanHR = 60/((sum(intervals)/1000)/len(intervals))
        MeanPPI = sum(intervals)/len(intervals)
        SDNNs = []
        RMSSDs = []
        indx = 0
        for i in intervals:
            SDNNs.append(abs(i-MeanPPI))
            if indx:
                RMSSDs.append(abs(intervals[indx-1]-i)**2)
            indx += 1
            
        SDNN = sum(SDNNs)/len(SDNNs)
        RMSSD = math.sqrt(sum(RMSSDs)/len(RMSSDs))
        
        stuffDict = {
            "Mean HR":MeanHR,
            "Mean PPI":MeanPPI,
            "SDNN":SDNN,
            "RMSSD":RMSSD,
        }
        
        oled.fill(0)
        indx = 0
        for k,v in stuffDict.items():
            t = k + ": {val:.2f}".format(val = v)
            oled.text(t, 0, 8*indx+7, 1)
            indx += 1
        oled.show()
        
    try:
        RotPush.fifo.get()
        mqtt_client = connect_mqtt()
        json_msg = ujson.dumps(stuffDict)
        mqtt_client.publish("pico/HRV",json_msg)
    except OSError as e:
        print(e)

def Kubios():
    # kubios credentials
    APIKEY = "pbZRUi49X48I56oL1Lq8y8NDjq6rPfzX3AQeNo3a"
    CLIENT_ID = "3pjgjdmamlj759te85icf0lucv"
    CLIENT_SECRET = "111fqsli1eo7mejcrlffbklvftcnfl4keoadrdv1o45vt9pndlef"

    LOGIN_URL = "https://kubioscloud.auth.eu-west-1.amazoncognito.com/login"
    TOKEN_URL = "https://kubioscloud.auth.eu-west-1.amazoncognito.com/oauth2/token"
    REDIRECT_URI = "https://analysis.kubioscloud.com/v1/portal/login"

    response = requests.post(
    url = TOKEN_URL,
    data = 'grant_type=client_credentials&client_id={}'.format(CLIENT_ID),
    headers = {'Content-Type':'application/x-www-form-urlencoded'},
    auth = (CLIENT_ID, CLIENT_SECRET))
    response = response.json() #Parse JSON response into a python dictionary
    access_token = response["access_token"] #Parse access token

    intervals = Measure30()
    
    dataset = {
        "type" : "RRI",
        "data" : intervals,
        "analysis": {"type": "readiness"}
        }

    response = requests.post(
    url = "https://analysis.kubioscloud.com/v2/analytics/analyze",
    headers = { "Authorization": "Bearer {}".format(access_token), #use access token to access your Kubios Cloud analysis session
    "X-Api-Key": APIKEY},
    json = dataset) #dataset will be automatically converted to JSON by the urequests library

    response = response.json()
    
    responseDict = {"timestamp":response["analysis"]["create_timestamp"][:22],
                    "Mean HR":response["analysis"]["mean_hr_bpm"],
                    "Mean PPI":response["analysis"]["mean_rr_ms"],
                    "RMSSD":response["analysis"]["rmssd_ms"],
                    "SDNN":response["analysis"]["sdnn_ms"],
                    "SNS":response["analysis"]["sns_index"],
                    "PNS":response["analysis"]["pns_index"]
                    }
    
    while not RotPush.fifo.has_data():
        oled.fill(0)
        indx = 1
        oled.text(str(responseDict["timestamp"][:10]), 0,0,1)
        for k,v in responseDict.items():
            if k != "timestamp":
                oled.text(k+": "+("%.2f" % v), 0, 8*indx+7, 1)
                indx += 1
        oled.show()    
    RotPush.fifo.get()
    historyRead = ujson.load(open("history.json", "r"))
    if len(historyRead) >= 5: historyRead.popitem()
    historyRead[responseDict["timestamp"][11:22]] = responseDict
    histFile = open("history.json","w")
    histFile.write(ujson.dumps(historyRead))
    histFile.close()

  
def History():
    with open("history.json") as historyFile:
        history = ujson.load(historyFile)
        SelectState = 0
        Selected = False
        print(history)
        while True:
            indx = 1
            if Rot.fifo.has_data():
                v = Rot.fifo.get()
                SelectState = (SelectState + v + int(v < 0)*(len(history)+1)) % (len(history)+1)
                
            if RotPush.fifo.has_data():
                Selected = not Selected
                RotPush.fifo.get()
            oled.fill(0)
            #print(list(history))
            if Selected:
                if SelectState == len(history): return
                selectedMeasure = history[list(history)[SelectState]]
                oled.text(selectedMeasure["timestamp"][11:19], 23, 0, 1)
                for k in selectedMeasure:
                    if k != "timestamp":
                        v = selectedMeasure[k]
                        oled.text(k + ": " + ("%.2f" % v), 0, 8*indx+7, 1)
                        indx += 1
            else:
                oled.text("History", 0, 0, 1)
                for k in history:
                    ts = history[k]["timestamp"]
                    oled.text(ts[5:10] + " " + ts[11:19] + " <"*(SelectState == indx-1), 0, 8*indx+7, 1)
                    indx += 1
                oled.text("Back" + " <"*(SelectState == len(history)),0,7+8*(len(history)+1),1)
            oled.show()

SelectState = 0
States = [["Heart Rate", HRMeasure], ["HRV", HRVMeasurement],["Kubios", Kubios], ["History", History]]

while True:
    if Rot.fifo.has_data():
        v = Rot.fifo.get()
        SelectState = (SelectState + v + int(v < 0)*len(States)) % len(States)
        
    oled.fill(0)
    for i in range(len(States)):
        text = States[i][0] + " <"*int(SelectState == i)
        oled.text(text, 0, 8*i)
    oled.show()
    
    
    
    if RotPush.fifo.has_data():
        RotPush.fifo.get()
        States[SelectState][1]()
    
    
    
    
    