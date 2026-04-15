
var containers = [];
var selectedContainer = {};
var machines = [];
var selectedMachine = {};
var _tab_name = "vnc";
var global_path = "/usr/local/share/dlbt_os/gen/"
var py_path = "/usr/local/share/dlbt_os/cockpit_vnc/py_backend/"
var _docker_images = [];
var _jupyter_images = [];
var _img_parse_count = 0;
var _img_parse_incomplete = "";
var vnc_server = 1;

_working_mode = "dev" //modes:  dev, production

function check_ports(){
    var mp = 8888;
    var conts = JSON.parse(data);
    conts.forEach(function(v){
        if(Number(v.port) < mp)
            mp = Number(v.port);        
    })
    var av_port = mp - 1;
    
}

function ping_success() {
    // result.style.color = "green";
    // result.innerHTML = "success";
    console.log("Success");
}

function ping_fail() {
    // result.style.color = "red";
    // result.innerHTML = "fail";
    console.log("Fail");

}

var _active_port = 0;
function start_vnc(){
    console.log("Starting vnc server...");
    // vncserver -geometry 1280x720 -depth 24 -SecurityTypes=none
    _active_port = 6085 + Math.floor(Math.random() * 100);
    
    if(_working_mode == "production"){
        cockpit.spawn([ py_path + "dist/start_vnc", "--port=" + _active_port])
        .stream(vnc_stream)
        .then(goToVnc)
        .catch(ping_fail);
    }
    else{
        cockpit.spawn(["python3", py_path + "start_vnc.py", "--port=" + _active_port])
        .stream(vnc_stream)
        .then(goToVnc)
        .catch(ping_fail);

    }
}

function vnc_stream(data){
    console.log(data);
    if(data.indexOf("dev:") >= 0){
        var s = data.indexOf("dev:");
        var e = data.indexOf("(");
    }
    if(data.indexOf("Press Ctrl-C") >= 0){
        var button = document.getElementById("run_button");
        var origin_url = window.location.hostname;        
        var vnc_url = "http://"+origin_url+":" + _active_port+ "/vnc.html";
        console.log("Setting href to: ", vnc_url);
        button.setAttribute("href", vnc_url);
        document.getElementById("status-label").innerHTML = "Started the VNC Server";
        button.disabled = false;
    }
}

// function start_noVnc(){
//     console.log("At least there too");    
//     // /usr/local/share/dlbt_os/py_backend/noVNC/utils/launch.sh --vnc localhost:5901
//     //"/usr/local/share/dlbt_os/py_backend/"
//     cockpit.spawn([py_path + "noNVC/utils/launch.sh", "--vnc", "localhost:5901"])
//         .stream((d)=>{console.log(d)})
//         .then(goToVnc)
//         .catch(ping_fail);
// }


function goToVnc(){
    console.log("Attempting to go to ", "http://"+origin_url+":6080");
    var origin_url = window.location.hostname;
    window.location = "http://"+origin_url+":6080/vnc.html";
}

let stateCheck = setInterval(() => {
    if (document.readyState === 'complete') {
        clearInterval(stateCheck);
        start_vnc();        
        var button = document.getElementById("run_button");
        document.getElementById("status-label").innerHTML = "Starting the VNC Server...";
        button.disabled = true;        
    }
}, 500);