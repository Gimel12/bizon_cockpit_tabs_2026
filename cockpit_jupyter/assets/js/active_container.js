
var runningContainers = [];
var selectedRunningContainer = {};

var _docker_containers = [];
var _jupyter_containers = [];
var _img_parse_count = 0;
var _img_parse_incomplete = "";
var py_path = "/usr/local/share/dlbt_os/cockpit_jupyter/py_backend/"
var container_marker = "-native_biz"
var jupyter_images = ["nvidia","jupyter_test", container_marker];
var _docker_images_src = {
    "jupyter_test": "images/jpg_44.jpg"
}

var _working_mode = "dev" // modes:  dev production

function getRunningContainers() {
    var runContainer1 = {
        name: "a",
        machineType: "type",
        dateCreated: "00/00/00",
        status: "able"
    };
    var runContainer2 = {
        name: "a",
        machineType: "type",
        dateCreated: "00/00/00",
        status: "able"
    };
    var runContainer3 = {
        name: "a",
        machineType: "type",
        dateCreated: "00/00/00",
        status: "able"
    };
    runningContainers = _jupyter_containers;

    // runningContainers.push(runContainer1, runContainer2, runContainer3);

}

function load_container_info(username){        
    console.log("in containers...")
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/read_containers"])    
        .stream(process_containers)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in load_container_info: ", o);
        });  
    }      
    else{
        cockpit.spawn(["/home/" + username + "/anaconda3/bin/python3",py_path + "read_containers.py"]) 
        .stream(process_containers)
        .then(ping_success)
        .catch(load_container_info_fsp);  
    }
}

function load_container_info_fsp(){
    console.log("failsafe");    
    cockpit.spawn(["python3",py_path + "read_containers.py"])    
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
    // console.log(conts);
    _jupyter_containers = conts.filter(function(v){    
        // for(var i =0;i<jupyter_images.length;i++)
        //     if(v.image.indexOf(jupyter_images[i]) > -1)
        //         return true;
        return true;        
    })

    for(var j=0;j<_jupyter_containers.length;j++){
        var cookie = getCookie(_jupyter_containers[j].name);
        if(cookie.length)
            _jupyter_containers[j].url = cookie;
    }
    if(_jupyter_containers.length > 0){
        var bt = document.getElementById("stop-all");
        bt.hidden = false;
    }
    else{
        var bt = document.getElementById("stop-all");
        bt.hidden = true;
    }
    console.log(_jupyter_containers);    
    writeContainersInTable();      
}

function open_container(url){
    console.log("here we are");
    window.open(url, "_blank");
}

function stop_container(event){
    console.log("stopping container..", event.target.id);
    var id = event.target.id.slice(event.target.id.indexOf("-")+1);
    stop_container_rel(id);
}

function stop_container_rel(id){
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/stop_container","--image="+id])
        .stream(on_stop_container)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in stop_container_rel: ", o);
        });   
    }     
    else{
        cockpit.spawn(["python3",py_path + "stop_container.py","--image="+id])
        .stream(on_stop_container)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in stop_container_rel: ", o);
        }); 
    }
}

function on_stop_container(data){
    console.log(data);
    load_container_info();
}

var _container_id = "";
var _container_idx = 0;
var _container_name = "";

function save_container(event){
    console.log("commiting container..", event.target.id);
    var sep = event.target.id.indexOf("-");
    var id = event.target.id.slice(event.target.id.indexOf("-")+1);
    // commit_container(id);
    _container_id = id;
    _container_idx = Number(event.target.id.slice(0,sep));
    _container_name = runningContainers[_container_idx].name;
    $("#header-commit-text").html("You are about to create an image from the container named <b>"+ _container_name + "</b>");
    var mod = document.getElementById("commit-modal");
    UIkit.modal(mod).show();
}

function commit_container(){
    var cmt_name = $("#commit-name").val() + container_marker;
    if(cmt_name.length == 0){
        UIkit.notification({
            message: 'The image name must not be empty.',
            status: 'danger',
            pos: 'top-center',
            timeout: 2000
        });
        return;
    }
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/commit_container","--image="+_container_id,"--name="+cmt_name])
        .stream(on_commit_container)
        .then(function(){
            var mod = document.getElementById("commit-modal");
            UIkit.modal(mod).hide();
            UIkit.notification({
                message: 'The image was created successfully.',
                status: 'success',
                pos: 'top-center',
                timeout: 2000
            });            
        })
        .catch((o) =>{
            console.log("Error in commit_container: ", o);
        }); 
    } 
    else{
        cockpit.spawn(["python3",py_path + "commit_container.py","--image="+_container_id,"--name="+cmt_name])
        .stream(on_commit_container)
        .then(function(){
            var mod = document.getElementById("commit-modal");
            UIkit.modal(mod).hide();
            UIkit.notification({
                message: 'The image was created successfully.',
                status: 'success',
                pos: 'top-center',
                timeout: 2000
            });            
        })
        .catch((o) =>{
            console.log("Error in commit_container: ", o);
        }); 
    }
}

function on_commit_container(data){
    console.log(data);
    // load_container_info();
}



function stop_all_containers(){
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/stop_all_containers"])
        .stream(on_stop_container)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in stop_all_containers: ", o);
        }); 
    }
    else{
        cockpit.spawn(["python3",py_path + "stop_all_containers.py"])
        .stream(on_stop_container)
        .then(ping_success)
        .catch((o) =>{
            console.log("Error in stop_all_containers: ", o);
        }); 
    }
}

function simple_refresh() {
    var cur_url = window.location.href;    
    window.location.replace(cur_url);
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
    var textTh2 = document.createTextNode("Container ID");
    th2.appendChild(textTh2);

    var th3 = document.createElement("th");
    var textTh3 = document.createTextNode("Tag");
    th3.appendChild(textTh3);

    var th4 = document.createElement("th");
    var textTh4 = document.createTextNode("Status");
    th4.appendChild(textTh4);

    var th5 = document.createElement("th");
    var textTh5 = document.createTextNode("Actions");
    th5.appendChild(textTh5);

    tr1.appendChild(th1)
    tr1.appendChild(th2)
    tr1.appendChild(th3)
    tr1.appendChild(th4)
    tr1.appendChild(th5)
    thead.appendChild(tr1);

    var tbody = document.createElement("tbody");
    // runningContainers = _jupyter_containers;

    runningContainers.forEach(function(container, index){
        var tr2 = document.createElement("tr");
        
        var td1 = document.createElement("td");
        var texttd1 = document.createTextNode(container.name);
        td1.appendChild(texttd1);

        var td2 = document.createElement("td");
        var texttd2 = document.createTextNode(container.id);
        td2.appendChild(texttd2);

        var td3 = document.createElement("td");
        var texttd3 = document.createTextNode(container.image);
        td3.appendChild(texttd3);

        var td4 = document.createElement("td");
        var texttd4 = document.createTextNode(container.status);
        td4.appendChild(texttd4);

        var td5 = document.createElement("td");
        var btn1 = document.createElement("a");
        btn1.classList.add("uk-button");
        btn1.classList.add("uk-button-default");
        btn1.classList.add("uk-margin-small-right");
        btn1.classList.add("uk-background-primary");
        btn1.classList.add("run-button");
        btn1.setAttribute("type", "button");
        btn1.setAttribute("href", container.url);
        btn1.setAttribute("target", "_blank");
        
        // btn1.setAttribute("onclick", "open_container('"+container.url+"');");

        btn1.innerHTML = "Open";
        var btn2 = document.createElement("button");
        btn2.classList.add("uk-button");
        btn2.classList.add("uk-button-default");
        btn2.classList.add("stop-button");
        btn2.setAttribute("id","stop-"+container.id);
        btn2.setAttribute("type", "button");
        btn2.innerHTML = "Stop";

        var btn3 = document.createElement("button");
        btn3.classList.add("uk-button");
        btn3.classList.add("uk-button-default");    
        btn3.classList.add("uk-margin-small-right");  
        btn3.classList.add("uk-background-secondary");  
        btn3.classList.add("run-button");
        btn3.setAttribute("id",index+"-"+container.id);
        btn3.setAttribute("type", "button");
        btn3.innerHTML = "Save";

        td5.appendChild(btn1);
        td5.appendChild(btn3);
        td5.appendChild(btn2);

        tr2.appendChild(td1);
        tr2.appendChild(td2);
        tr2.appendChild(td3);
        tr2.appendChild(td4);
        tr2.appendChild(td5);
        tbody.appendChild(tr2);
        btn2.addEventListener("click",stop_container);
        btn3.addEventListener("click",save_container);

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


let stateCheck1 = setInterval(() => {
    if (document.readyState === 'complete') {
        clearInterval(stateCheck1);
        document.body.style = "overflow:auto;";
        cockpit.user().then(user => {
            load_container_info(username = user.name);
            var button = document.getElementById("stop-all");
            button.addEventListener("click", stop_all_containers);    
        })
        $("#commit-container-btn").click(commit_container);
        // load_container_info();
        // var button = document.getElementById("stop-all");
        // button.addEventListener("click", stop_all_containers);        
        
    }

}, 100);