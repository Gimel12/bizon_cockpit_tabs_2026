
var runningContainers = [];
var selectedRunningContainer = {};

var _docker_containers = [];
var _jupyter_containers = [];
var _img_parse_count = 0;
var _img_parse_incomplete = "";
var py_path = "/usr/local/share/dlbt_os/cockpit_containers/py_backend/"
var global_path = "/usr/local/share/dlbt_os/gen/"
var container_marker = "-native_biz";
var jupyter_images = ["nvidia","jupyter_test"]
var _docker_images_src = {
    "jupyter_test": "images/jpg_44.jpg"
}

var _working_mode = "dev"; // modes:  dev production
var _tab_name = "containers";

function clean_name(name){
    var idx = name.indexOf(container_marker);
    if(idx < 0)
        return name;
    return name.slice(0,idx) + name.slice(idx+container_marker.length);    
}

function getRunningContainers() {
    runningContainers = _jupyter_containers;
}

function load_container_info(username){        
    // cockpit.spawn([py_path + "read_images"]) 
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/read_images"])   
        .stream(process_containers)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in load_container_info: ", o);
        });    
    }   
    else{
        cockpit.spawn(["python3",py_path + "read_images.py"])    
            .stream(process_containers)
            .then(ping_success)
            .catch((o) =>{
                // load_container_info();
                console.log("Error in load_container_info: ", o);
            });    
    }
}

function load_container_info_fsp(){
    console.log("failsafe");    
    cockpit.spawn(["python3",py_path + "read_images.py"])    
        .stream(process_containers)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in load_container_info_fsp: ", o);
        });        
}

function getCookie(cname) {
    var name = cname + "=";
    var decodedCookie = decodeURIComponent(document.cookie);
    var ca = decodedCookie.split(';');
    for(var i = 0; i <ca.length; i++) {
      var c = ca[i];
      while (c.charAt(0) == ' ') {
        c = c.substring(1);
      }
      if (c.indexOf(name) == 0) {
        return c.substring(name.length, c.length);
      }
    }
    return "";
  }


function process_containers(data){
    
    // console.log(data);
    var conts = JSON.parse(data);
    _jupyter_containers = conts; 
    writeContainersInTable();      
}

function prettify_date(ds){
    return ds.slice(0,10) + " " + ds.slice(11,16);
}

function prettify_size(size){
    var kbd = Math.pow(2,10);
    var mbd = Math.pow(2,20);
    var gbd = Math.pow(2,30);

    if(size < mbd){
        return (size/kbd).toFixed(2) + "kB";
    }
    else if(size < gbd){
        return (size/mbd).toFixed(2) + "MB";
    }
    else{
        return (size/gbd).toFixed(2) + "GB";
    }
}

function writeContainersInTable() {

    getRunningContainers();

    var runContainerTable = document.getElementById("run-container");
    runContainerTable.innerHTML = "";
    
    var thead = document.createElement("thead");
        
    var tr1 = document.createElement("tr");
    
    var th1 = document.createElement("th");
    th1.classList.add("uk-width-small");
    var textTh1 = document.createTextNode("Name");
    th1.appendChild(textTh1);

    var th2 = document.createElement("th");
    var textTh2 = document.createTextNode("Image ID");
    th2.appendChild(textTh2);

    var th3 = document.createElement("th");
    var textTh3 = document.createTextNode("Tag");
    th3.appendChild(textTh3);

    var th4 = document.createElement("th");
    var textTh4 = document.createTextNode("Created");
    th4.appendChild(textTh4);

    var th5 = document.createElement("th");
    var textTh5 = document.createTextNode("Size");
    th5.appendChild(textTh5);

    var th6 = document.createElement("th");
    var textTh6 = document.createTextNode("Actions");
    th6.appendChild(textTh6);

    tr1.appendChild(th1)
    tr1.appendChild(th2)
    tr1.appendChild(th3)
    tr1.appendChild(th4)
    tr1.appendChild(th5)
    tr1.appendChild(th6)
    thead.appendChild(tr1);

    var tbody = document.createElement("tbody");
    // runningContainers = _jupyter_containers;
    console.log("r", runningContainers);
    runningContainers.forEach(function(container, index){
        var cname = clean_name(container.title);
        var tr2 = document.createElement("tr");
        
        var td1 = document.createElement("td");
        var texttd1 = document.createTextNode(cname.slice(0,cname.indexOf(":")));        

        td1.appendChild(texttd1);

        var td2 = document.createElement("td");
        var texttd2 = document.createTextNode(container.id);
        td2.appendChild(texttd2);

        var td3 = document.createElement("td");
        var texttd3 = document.createTextNode(cname.slice(cname.indexOf(":")+1,cname.length));
        td3.appendChild(texttd3);

        var td4 = document.createElement("td");
        var texttd4 = document.createTextNode(prettify_date(container.created));
        td4.appendChild(texttd4);

        var td5 = document.createElement("td");
        var texttd5 = document.createTextNode(prettify_size(container.size));
        td5.appendChild(texttd5);

        var td6 = document.createElement("td");
        var btn2 = document.createElement("button");
        btn2.classList.add("uk-button");
        btn2.classList.add("uk-button-default");
        btn2.classList.add("stop-button");
        btn2.setAttribute("id",index+ "-"+container.id);
        btn2.setAttribute("type", "button");
        btn2.innerHTML = "Delete";
        td6.appendChild(btn2);

        tr2.appendChild(td1);
        tr2.appendChild(td2);
        tr2.appendChild(td3);
        tr2.appendChild(td4);
        tr2.appendChild(td5);
        tr2.appendChild(td6);
        tbody.appendChild(tr2);
        btn2.addEventListener("click",erase_container);

        // document.addEventListener("onclick")
        // button.addEventListener("click", load_containers);
        
    })

    runContainerTable.appendChild(thead);
    runContainerTable.appendChild(tbody);
}


function ping_success() {
    // result.style.color = "green";
    // result.innerHTML = "success";
    console.log("Success");
}

function ping_fail(data) {
    // result.style.color = "red";
    // result.innerHTML = "fail";
    console.log("Fail", data);

}

var _image_id = "";
var _image_idx = -1;
var _image_name = "";
function erase_container(event){    
    console.log(event.target.id);
    var sep = event.target.id.indexOf("-");
    _image_idx = Number(event.target.id.slice(0,sep));
    _image_id = event.target.id.slice(sep+1);
    var mod = document.getElementById("modal-sections");
    var name = runningContainers[_image_idx].title;
    var id = runningContainers[_image_idx].id;
    _image_name = name;
    var text = "You are about to delete the image <b>" + name + "</b> with id <b>"+ id + "</b> permanently. This action cannot be undone. Are you sure?";
    $("#delete-text").html(text);
    UIkit.modal(mod).show();
}

function real_erase_image(){
    console.log("erasing image..", _image_name);
    // cockpit.spawn([py_path + "erase_image","--image_id="+_image_name])
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/erase_image","--image_id="+_image_name])
        .stream(on_erase_image)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in real_erase_image: ", o);
        }); 
    }
    else{
        cockpit.spawn(["python3",py_path + "erase_image.py","--image_id="+_image_name])
        .stream(on_erase_image)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in real_erase_image: ", o);
        }); 
    }    
}


function on_erase_image(data){
    console.log(data);
    if(data.indexOf("Error") < 0){
        var mod = document.getElementById("modal-sections");
        UIkit.modal(mod).hide();
        load_container_info(_user.name);
    }    
}

_user = null;
let stateCheck1 = setInterval(() => {
    if (document.readyState === 'complete') {
        clearInterval(stateCheck1);
        load_container_info();
        // var button = document.getElementById("stop-all");
        // button.addEventListener("click", stop_all_containers);        
        cockpit.user().then(user =>{
            console.log(user);
            load_container_info(username = user.name);
            _user = user;
        });
        $("#delete-container-btn").click(real_erase_image);
    }
    // var promise = cockpit.user();
    

}, 100);